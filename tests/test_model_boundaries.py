"""Whole pipeline swaps answer models without rebuilding source/vector stores."""
import json
import sqlite3
from pathlib import Path
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from kezohar import api, config, llm
from kezohar.agent import Agent
from kezohar.answer_models import ConfiguredAnswerModel, register_answer_provider
from kezohar.embeddings import VectorIndexSpec, VectorIndexMismatch, MockEmbeddingModel
from kezohar.hybrid import HybridSearch, FederatedSearch
from kezohar.knowledge import KnowledgeBase
from kezohar.library_search import SQLiteLibrarySearch, rebuild_fts
from kezohar.models import Source
from kezohar.vector import MockVectorStore
from kezohar.web_research import WebResearchEngine
from kezohar.verification import ExtractiveSourceVerifier


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for key,value in {'LLM_PROVIDER':'openai-compatible','LLM_MODEL':'mock-answer-a',
                      'LLM_BASE_URL':'http://mock.invalid/v1','EMBEDDINGS_PROVIDER':'mock',
                      'EMBEDDINGS_MODEL':'hash-trigram-v1','EMBEDDINGS_DIMENSIONS':'128',
                      'EMBEDDINGS_REVISION':'1'}.items():
        monkeypatch.setenv(key,value)


def test_two_configured_mock_models_work_across_api_search_web_verification_and_sse(tmp_path,monkeypatch):
    # Test-source sentences, not an independently verified halachic reference.
    sentences={'mock-answer-a':'אורז מבושל ברכתו מזונות.',
               'mock-answer-b':'אורז ברכתו האחרונה בורא נפשות.'}
    source=Source(work_title='ספר בדיקה',source_id='stable-rice',reference='בדיקת מודל א:א',text=' '.join(sentences.values()))
    store=tmp_path/'sources.jsonl';store.write_text(json.dumps(source.to_dict(),ensure_ascii=False)+'\n')
    dbpath=tmp_path/'library.sqlite3'
    with sqlite3.connect(str(dbpath)) as db:
        db.execute('CREATE TABLE records(id TEXT PRIMARY KEY, file TEXT, payload TEXT)')
        db.execute('INSERT INTO records VALUES (?,?,?)',(source.source_id,'fixture',json.dumps(source.to_dict())))
        rebuild_fts(db)
    knowledge=KnowledgeBase(store_path=store)
    knowledge.search=FederatedSearch(knowledge.search,[SQLiteLibrarySearch(dbpath)])
    vector=knowledge.search.vector
    vectors_before=list(vector.vecs)
    engine=WebResearchEngine()
    monkeypatch.setattr(engine,'research',lambda *a,**k:{'sources':[source.to_dict()], 'answer':'', 'comparisons':[]})
    ag=Agent(knowledge=knowledge,research_engine=engine)
    monkeypatch.setattr(api,'_agent',ag)
    monkeypatch.setattr(api,'_hits',{})
    calls=[]
    def transport(base_url,path,body,**kwargs):
        assert base_url=='http://mock.invalid/v1' and path=='/chat/completions'
        assert 'בדיקת מודל א:א' in body['messages'][1]['content']
        calls.append(body['model'])
        return {'choices':[{'message':{'content':'״'+sentences[body['model']]+'״ (בדיקת מודל א:א).'}}]}
    monkeypatch.setattr(llm,'_post',transport)
    monkeypatch.setattr(llm,'check_health',lambda *a,**k:(True,list(sentences)))
    # Any attempt to recreate retrieval after the answer-model switch fails.
    monkeypatch.setattr('kezohar.bm25.BM25Index.build',lambda *a,**k:pytest.fail('unexpected corpus rebuild'))
    artifacts={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in (store,dbpath)}
    client=TestClient(api.app)
    for model in sentences:
        monkeypatch.setenv('LLM_MODEL',model)
        health=client.get('/health').json()
        assert health['llm_ok'] and health['retrieval']['vector_index']==vector.index_spec.manifest()
        found=client.post('/search',json={'query':'אורז'}).json()['results']
        assert found[0]['source_id']==source.source_id
        result=client.post('/ask',json={'question':'מה מברכים על אורז?'}).json()
        assert result['answer']=='״'+sentences[model]+'״ (בדיקת מודל א:א).'
        assert result['verdict']=='ok' and not result.get('cached')
        assert result['verification']['support']=='exact-extract-only'
        assert client.post('/ask',json={'question':'מה מברכים על אורז?'}).json()['cached']
        stream=client.post('/ask',json={'question':'ברכת אורז?', 'stream':True}).text
        assert stream.index('event: sources')<stream.index('event: answer')<stream.index('event: done')
        researched=client.post('/research',json={'question':'מה מברכים על אורז?'}).json()
        assert researched['mode']=='web-llm-verified' and researched['answer']==result['answer']
        assert client.post('/ask',json={'question':'מה מזג האוויר?'}).json()['mode']=='refuse'
        assert client.post('/ask',json={'question':'מתי שקיעה היום בנתיבות?'}).json()['mode']=='fast'
        assert knowledge.search.vector is vector and vector.vecs==vectors_before
        assert {p:(p.read_bytes(),p.stat().st_mtime_ns) for p in artifacts}==artifacts
    assert set(calls)==set(sentences)


def test_future_provider_registration_does_not_change_agent_core(monkeypatch):
    from kezohar import answer_models
    monkeypatch.setattr(answer_models,'_PROVIDERS',dict(answer_models._PROVIDERS))
    class LocalDummy:
        def __init__(self,settings):self.identity=settings
        def generate(self,q,sources,timeout=4.5):return {'answer':'״אורז מזונות״ (בדיקה א:א).'}
        def health(self,timeout=8):return True,['local-dummy']
    register_answer_provider('local-dummy',LocalDummy)
    monkeypatch.setenv('LLM_PROVIDER','local-dummy')
    ag=Agent(sources=[Source(work_title='ספר בדיקה',source_id='a',text='אורז מזונות',reference='בדיקה א:א')])
    assert ag.ask('ברכת אורז')['verdict']=='ok'
    assert ag.answer_model.health()[0]
    with pytest.raises(ValueError):register_answer_provider('local-dummy',LocalDummy)


def test_unknown_provider_fails_without_unintended_fallback(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER','not-installed')
    with pytest.raises(ValueError,match='unknown answer provider'):
        ConfiguredAnswerModel().generate('שאלה',[])


@pytest.mark.parametrize('change', [
    {'model':'different-embedding'}, {'provider':'different-provider'},
    {'dimensions':64}, {'revision':'2'},
])
def test_embedding_changes_require_new_index_namespace(change):
    original=VectorIndexSpec.from_settings(config.embedding_settings())
    changed=replace(original,**change)
    assert changed.namespace!=original.namespace
    with pytest.raises(VectorIndexMismatch):changed.check_manifest(original.manifest())
    changed.check_manifest(changed.manifest())


def test_answer_model_change_does_not_change_embedding_identity(monkeypatch):
    embeddings=config.embedding_settings()
    original=VectorIndexSpec.from_settings(embeddings).manifest()
    monkeypatch.setenv('LLM_MODEL','another-answer-model')
    monkeypatch.setenv('LLM_PROVIDER','another-answer-provider')
    assert config.embedding_settings()==embeddings
    assert VectorIndexSpec.from_settings(config.embedding_settings()).manifest()==original


def test_embedding_configuration_change_preserves_lexical_search_and_original_vectors(monkeypatch):
    h=HybridSearch([Source(work_title='ספר בדיקה',source_id='a',text='אורז מזונות')])
    original=list(h.vector.vecs)
    monkeypatch.setenv('EMBEDDINGS_DIMENSIONS','64')
    result=h.search('אורז')
    assert result and 'vector-mock' not in result[0]['backend']
    assert h.vector_status=='reindex-required' and h.vector.vecs==original
    assert KnowledgeBase(search_engine=h).status()['vector_status']=='reindex-required'
    with pytest.raises(VectorIndexMismatch):h.vector.search('אורז')
    rebuilt=HybridSearch([Source(work_title='ספר בדיקה',source_id='a',text='אורז מזונות')])
    assert rebuilt.vector.index_spec.namespace!=h.vector.index_spec.namespace
    assert len(rebuilt.vector.vecs[0])==64 and rebuilt.search('אורז')


def test_bad_embedding_dimensions_or_nonfinite_values_never_enter_store():
    class BadEmbedder:
        spec=VectorIndexSpec('test','broken',2,'1')
        def embed(self,text):return [float('nan'),0]
    vector=MockVectorStore(embedding_model=BadEmbedder())
    with pytest.raises(VectorIndexMismatch):vector.add([Source(work_title='ספר בדיקה',source_id='a',text='אורז')])
    assert not vector.docs and not vector.vecs


def test_embedding_provider_injection_is_independent(monkeypatch):
    from kezohar import embeddings
    monkeypatch.setattr(embeddings,'_PROVIDERS',dict(embeddings._PROVIDERS))
    class FakeEmbedding:
        def __init__(self,settings):self.spec=VectorIndexSpec.from_settings(settings)
        def embed(self,text):return [1.0]*self.spec.dimensions
    embeddings.register_embedding_provider('test-local',FakeEmbedding)
    monkeypatch.setenv('EMBEDDINGS_PROVIDER','test-local')
    monkeypatch.setenv('EMBEDDINGS_MODEL','test-embedding-a')
    vector=MockVectorStore();vector.add([Source(work_title='ספר בדיקה',source_id='a',text='אורז')])
    assert vector.search('אורז')
    monkeypatch.setenv('EMBEDDINGS_MODEL','test-embedding-b')
    with pytest.raises(VectorIndexMismatch):vector.search('אורז')
    assert config.answer_settings().model=='mock-answer-a'


def test_verifier_checks_each_cited_source_not_unquoted_relevant_sources():
    relevant={'source_id':'a','reference':'בדיקה א:א','text':'אורז מזונות'}
    unrelated={'source_id':'b','reference':'בדיקה ב:א','text':'בשר שש שעות'}
    result=ExtractiveSourceVerifier().verify('ברכת אורז','״בשר שש שעות״ (בדיקה ב:א).',[relevant,unrelated])
    assert result['verdict']=='irrelevant'
