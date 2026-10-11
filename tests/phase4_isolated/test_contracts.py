"""One requirement per test; all text/catalogs/owners are deliberately synthetic.

Run through scripts/run_phase4_isolated.py ONLY. Failing requirements are kept
as failures, never xfailed or weakened to match current implementation.
"""
import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest

if not os.environ.get('PHASE4_ISOLATED_RUN'):
    pytest.skip('requires guarded phase4 runner', allow_module_level=True)

from kezohar import api, fastpath, semantic_claims, question_understanding as qu
from kezohar.agent import Agent
from kezohar.models import Source
from kezohar.verification import ExtractiveSourceVerifier
from kezohar.answer_composition import VerifiedAnswerComposer
from kezohar.request_budget import RequestBudget, BudgetedAnswerModel, BudgetExceeded
from kezohar.conversation_state import ConversationStore, ConversationConflict
from kezohar.source_graph import HalachicSourceGraph
from kezohar.hybrid import HybridSearch, FederatedSearch, rrf_fuse
from kezohar.knowledge import KnowledgeBase
from kezohar.library_search import SQLiteLibrarySearch, rebuild_fts
from kezohar import locator_resolution as loc
from kezohar.locator_hierarchy import hierarchy_diagnostics
from kezohar.hebrew import normalize
from kezohar import config, answer_models, embeddings

Q = 'בדיקת מקור סינתטי CASE_RICE'
TEXT = 'בדיקת מקור סינתטי: רק כאשר דגל בדיקה פעיל, יש להציג סמל אלפא.'
CLAIM = 'כאשר דגל בדיקה פעיל מציגים סמל אלפא.'

def source(sid='s1', text=TEXT, **updates):
    s = Source(source_id=sid, work_title='ספר בדיקה מלאכותי', reference='בדיקה בלבד א:א',
               text=text, normalized_text=normalize(text), version='synthetic-edition-1',
               metadata={'rag_answers_allowed':True}).to_dict()
    s.update(updates)
    return s

def quote(s):
    return json.dumps({'quotes':[{'source_id':s['source_id'], 'quote':s['text']}]}, ensure_ascii=False)

def claim(s, text=CLAIM):
    return json.dumps({'claims':[{'source_id':s['source_id'], 'evidence_id':'test-unit', 'text':text}]}, ensure_ascii=False)

class FixedAnswer:
    def __init__(self, output=None, name='fixed-a', hook=None):
        self.identity = config.AnswerSettings('isolated-fixed', name, '')
        self.output, self.hook, self.calls = output, hook, []
    def generate(self, question, sources, timeout=4.5):
        self.calls.append((question, copy.deepcopy(sources), timeout))
        if self.hook: self.hook()
        return {'answer':self.output if self.output is not None else quote(sources[0])}
    def health(self, **kwargs): raise AssertionError('health not authorized')

@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    # Import-time safety is supplied by runner; per-test state/paths reset here.
    monkeypatch.setattr(api, '_agent', None)
    monkeypatch.setattr(api, '_hits', {})
    monkeypatch.setattr(fastpath, 'is_out_of_scope', lambda q: q == 'TEST_REFUSE')
    monkeypatch.setattr(fastpath, 'handle', lambda q, **kw: {'answer':'תוצאת בדיקה קבועה', 'kind':'test-fast'} if q=='TEST_FAST' else None)
    intent = lambda q: 'rice' if 'CASE_RICE' in q else 'general-halacha'
    monkeypatch.setattr(semantic_claims, 'question_intent', intent)
    monkeypatch.setattr(qu, 'question_intent', intent)
    catalog = tmp_path/'catalog.json'
    catalog.write_text(json.dumps({'rules':[]}))
    monkeypatch.setenv('CLAIM_CATALOG_PATH', str(catalog))
    monkeypatch.setattr(loc, 'ROOT', tmp_path)
    monkeypatch.setattr(loc, 'REGISTRY', tmp_path/'registry.json')
    monkeypatch.setattr(loc, 'RESOLUTIONS', tmp_path/'overlay.json')
    return tmp_path

def agent(sources=None, model=None):
    # No actual Embeddings provider: lexical-only index for ordinary contracts.
    items = [Source.from_dict(s) for s in (sources or [source()])]
    return Agent(knowledge=KnowledgeBase(search_engine=HybridSearch(items, vector_store=False)),
                 answer_model=model or FixedAnswer())

def install_catalog(tmp_path, s):
    rule = {'intent':'rice', 'evidence_id':'test-unit', 'source_id':s['source_id'],
            'source_text_sha256':hashlib.sha256(s['text'].encode()).hexdigest(),
            'work_title':s['work_title'], 'reference':s['reference'], 'version':s['version'],
            'quote':s['text'], 'conditions':['דגל בדיקה פעיל'], 'variants':[CLAIM],
            'contradicted_examples':['כאשר דגל בדיקה פעיל אין להציג סמל אלפא.']}
    (tmp_path/'catalog.json').write_text(json.dumps({'rules':[rule]}, ensure_ascii=False))
    return rule

def complete(**updates):
    return dict(rice_form='cooked', **updates)

def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr('kezohar.request_budget.time.monotonic', lambda:now[0])
    return now

def request(path, body=None, method='POST', raw=None):
    async def run():
        async with __import__('httpx').AsyncClient(transport=__import__('httpx').ASGITransport(app=api.app),
                                                 base_url='http://in-process.invalid') as c:
            if raw is not None: return await c.request(method, path, content=raw)
            return await c.request(method, path, json=body)
    return asyncio.run(run())

def events(raw):
    return [(part.splitlines()[0][7:], json.loads(part.splitlines()[1][6:]))
            for part in raw.strip().split('\n\n')]

def test_T01_fast_refuse_no_retrieval_generation_or_persistence(monkeypatch):
    a=agent(); before=copy.deepcopy(a.search.bm25.docs)
    monkeypatch.setattr(a, 'search_only', lambda *a,**k:pytest.fail('unexpected search'))
    for q,mode in [('TEST_FAST','fast'),('TEST_REFUSE','refuse')]:
        r=a.converse(q)
        assert r['mode']==mode and r['sources']==[]
    assert a.answer_model.calls==[] and a.search.bm25.docs==before

def test_T02_missing_and_conflicting_slots_stop_before_search(monkeypatch):
    a=agent()
    monkeypatch.setattr(a,'search_only',lambda *a,**kw:pytest.fail('search before clarification'))
    for q,slots in [(Q,None),(Q+' לא מבושל', complete())]:
        r=a.converse(q,circumstances=slots)
        assert r['mode']=='clarification' and not r['halachic_verified']
    assert not a.answer_model.calls

def test_T03_json_and_sse_effective_questions_match_three_traditions(monkeypatch):
    for tradition in ('sephardi','ashkenazi','both'):
        a=agent(); queries=[]
        monkeypatch.setattr(a,'search_only',lambda q,**kw:queries.append(q) or [source()])
        monkeypatch.setattr(api,'_agent',a)
        slots=complete(tradition=tradition)
        r=request('/ask',{'question':Q,'circumstances':slots})
        streamed=request('/ask',{'question':Q,'circumstances':slots,'stream':True})
        assert r.status_code==streamed.status_code==200
        assert queries[0]==queries[1]==a.answer_model.calls[0][0]==a.answer_model.calls[1][0]
        assert r.json()['question_analysis']['circumstances']==slots

def test_T04_reuse_retrieval_and_verify_actual_sent_sources(monkeypatch):
    a=agent(); seen=[]; original=a.source_verifier.verify
    monkeypatch.setattr(a,'search_only',lambda *a,**k:pytest.fail('duplicate search'))
    monkeypatch.setattr(a.source_verifier,'verify',lambda q,out,s:seen.append(copy.deepcopy(s)) or original(q,out,s))
    r=a.converse(Q, circumstances=complete(), retrieved_sources=[source()])
    assert r['orchestration']['retrieval_reused'] and len(a.answer_model.calls)==1
    assert seen==[a.answer_model.calls[0][1]]

def test_T05_research_mock_fetch_failure_keeps_local_verified_source(monkeypatch):
    from kezohar.web_research import WebResearchEngine
    class Search:
        def search(self,*a):return ['https://fixture.invalid/a']
    def fetch(*a):raise OSError('synthetic unavailable page')
    engine=WebResearchEngine(searcher=Search(),fetcher=fetch,sites={'fixture.invalid':{}},licenses={})
    a=agent();a.research_engine=engine
    r=a.converse(Q,circumstances=complete(),research=True,retrieved_sources=[source()])
    assert r['errors'] and r['verification']['verdict']=='ok'
    assert r['sources'][0]['source_id']=='s1' and not r['halachic_verified']

def test_T06_utf8_limit_drops_whole_sources(monkeypatch):
    from kezohar.llm import build_messages
    small=source(); big=source('s2',text=TEXT*1000)
    limit=sum(len(m['content'].encode()) for m in build_messages(Q,[small]))+50
    b=RequestBudget(max_context_bytes=max(4096,limit)); chosen=b.fit(Q,[small,big])
    assert chosen==[small] and b.dropped_source_ids==['s2']
    assert b.context_bytes<=b.max_context_bytes and chosen[0]['text']==TEXT

def test_T07_all_oversized_sources_stop_without_generation():
    b=RequestBudget(max_context_bytes=4096);model=FixedAnswer()
    with pytest.raises(BudgetExceeded):BudgetedAnswerModel(model,b).generate(Q,[source(text=TEXT*1000)])
    assert not model.calls and b.calls==0 and b.reason

def test_T08_fake_deadline_prevents_start_and_rejects_late_output(monkeypatch):
    now=clock(monkeypatch); b=RequestBudget(seconds=1); now[0]=2
    m=FixedAnswer()
    with pytest.raises(BudgetExceeded):BudgetedAnswerModel(m,b).generate(Q,[source()])
    assert not m.calls
    now[0]=0; b=RequestBudget(seconds=1);m=FixedAnswer(hook=lambda:now.__setitem__(0,2))
    with pytest.raises(BudgetExceeded):BudgetedAnswerModel(m,b).generate(Q,[source()])
    assert len(m.calls)==1 and 'deadline' in b.reason

def test_T09_zero_one_and_second_call_no_retry():
    for count in (0,1):
        b=RequestBudget(max_calls=count);m=FixedAnswer();gen=BudgetedAnswerModel(m,b)
        if count:gen.generate(Q,[source()])
        with pytest.raises(BudgetExceeded):gen.generate(Q,[source()])
        assert len(m.calls)==count and b.calls==count

def test_T10_budget_failure_and_context_changes_do_not_poison_cache():
    a=agent()
    stopped=a.converse(Q,circumstances=complete(),request_budget=RequestBudget(max_calls=0),retrieved_sources=[source()])
    assert stopped['verdict']=='budget_exhausted'
    for form in ('cooked','raw'):
        r=a.converse(Q,circumstances={'rice_form':form},retrieved_sources=[source()])
        assert r['verdict']=='ok' and not r.get('cached')
    assert len(a.answer_model.calls)==2 and not a._cache

def test_T11_exact_quote_identity_not_general_entailment():
    s=source();v=ExtractiveSourceVerifier().verify('בדיקת מקור סינתטי',quote(s),[s])
    r=VerifiedAnswerComposer().compose({'answer':v['rendered_answer'],'sources':[s],'verification':v,'verdict':v['verdict']})
    assert v['verdict']=='ok' and v['checks']['source_exists']=='passed'
    assert r['verification_layers']['quotation_integrity']=='passed-exact-extract'
    assert not r['verification_layers']['claim_support']['general_entailment_verified']
    assert not r['halachic_verified'] and r['human_review']=='required'

def test_T12_fabricated_or_colliding_id_blocked():
    s=source();v=ExtractiveSourceVerifier()
    assert v.verify(Q,quote(source('invented')),[s])['verdict']!='ok'
    other=source(text=TEXT+' נוסח אחר')
    assert v.verify(Q,quote(s),[s,other])['verdict']=='invalid_citation'

def test_T13_budget_dropped_source_cannot_be_cited():
    small=source();big=source('s2',text=TEXT*1000)
    a=agent(model=FixedAnswer(output=quote(big)))
    r=a.converse(Q,circumstances=complete(),retrieved_sources=[small,big],request_budget=RequestBudget(max_context_bytes=6000))
    assert r['verdict']=='invalid_citation' and [s['source_id'] for s in r['sources']]==['s1']
    assert not r['structured_answer']['sources']

def test_T14_changed_or_condition_truncated_quote_blocked():
    s=source();v=ExtractiveSourceVerifier();issues=[]
    # Positive control and a topic retained inside the shortened quotation:
    # rejection must not be caused merely by losing every query keyword.
    q='סמל אלפא'
    assert v.verify(q,quote(s),[s])['verdict']=='ok'
    for text in [TEXT.replace('אלפא','בטא'),'יש להציג סמל אלפא.']:
        out=json.dumps({'quotes':[{'source_id':'s1','quote':text}]})
        if v.verify(q,out,[s])['verdict']=='ok':issues.append(text)
    assert not issues, 'accepted altered/condition-truncated exact substring: '+repr(issues)

def test_T15_fluent_similar_uncatalogued_claim_not_approved():
    s=source();r=ExtractiveSourceVerifier().verify(Q,claim(s),[s])
    assert r['verdict']=='review_required' and not r['halachic_verified']

def test_T16_changed_text_locator_or_edition_invalidates_unit(tmp_path):
    s=source();install_catalog(tmp_path,s);v=ExtractiveSourceVerifier();issues=[]
    assert v.verify(Q,claim(s),[s])['verdict']=='ok'
    for field,value in [('text',TEXT+' תנאי נוסף'),('reference','בדיקה אחרת'),('version','synthetic-edition-2')]:
        changed=dict(s,**{field:value})
        if v.verify(Q,claim(s),[changed])['verdict']=='ok':issues.append(field)
    assert not issues, 'stale evidence accepted after identity change: '+repr(issues)

def test_T17_added_claim_and_omitted_condition_rejected(tmp_path):
    s=source();install_catalog(tmp_path,s);v=ExtractiveSourceVerifier()
    for text in [CLAIM+' גם ללא דגל.', 'מציגים סמל אלפא.']:
        assert v.verify(Q,claim(s,text),[s])['verdict']=='review_required'

def test_T18_search_only_ambiguous_excluded_copyright_alone_allowed():
    v=ExtractiveSourceVerifier()
    for metadata in [{'rag_answers_allowed':False},{'rag_answers_allowed':True,'locator_status':'ambiguous-file-fields'}]:
        s=source(metadata=metadata)
        assert not v.eligible_sources(Q,[s]) and v.verify(Q,quote(s),[s])['verdict']!='ok'
    s=source(license='copyrighted-with-synthetic-owner-grant')
    assert v.eligible_sources(Q,[s])==[s]

def test_T19_civil_title_or_path_cannot_be_used_as_ruling():
    v=ExtractiveSourceVerifier()
    for updates in [{'work_title':'תקנות בדיקה מלאכותית'},
                    {'work_title':'ספר הלכה בדיקה','source_url':'https://fixture.invalid/תקנות_בדיקה'}]:
        s=source(**updates)
        assert not v.eligible_sources(Q,[s]) and v.verify(Q,quote(s),[s])['verdict']=='irrelevant'

@pytest.mark.skip(reason='T20 historical Qwen fixture is real halachic content; synthetic-only authorization excludes it')
def test_T20_original_qwen_waiting_fixture():
    pass

def memory(tmp_path, **kw):return ConversationStore(tmp_path/'memory'/'state.sqlite3',**kw)

class MemoryAgent:
    def __init__(self):self.calls=[]
    def converse(self,q,**kw):
        self.calls.append((q,copy.deepcopy(kw)))
        return {'answer':'תוצאת תחליף בלבד','verdict':'test-only','halachic_verified':False}

def test_T21_foreign_owner_load_denied(tmp_path):
    store=memory(tmp_path);cid=store.create('owner-a')
    with pytest.raises(KeyError):store.load('owner-b',cid)
    assert store.load('owner-a',cid)[0]==0

def test_T22_foreign_owner_turn_denied_before_agent(tmp_path):
    store=memory(tmp_path);cid=store.create('owner-a');a=MemoryAgent()
    with pytest.raises(KeyError):store.turn(a,'owner-b',cid,Q,circumstances=complete())
    assert not a.calls and store.load('owner-a',cid)[0]==0

def test_T23_foreign_save_delete_leave_original_unchanged(tmp_path):
    store=memory(tmp_path);cid=store.create('owner-a');rev,state=store.load('owner-a',cid)
    with pytest.raises(ConversationConflict):store.save('owner-b',cid,rev,dict(state,root_question='FOREIGN'))
    assert not store.delete('owner-b',cid) and store.load('owner-a',cid)==(rev,state)

def test_T24_parallel_owners_and_conversations_isolated(tmp_path):
    store=memory(tmp_path);keys=[('a',store.create('a')),('a',store.create('a')),('b',store.create('b'))]
    def write(i):
        owner,cid=keys[i];rev,state=store.load(owner,cid)
        state.update(root_question='private-'+str(i),user_facts={'test-marker':str(i)},system_hypotheses=['hyp-'+str(i)])
        store.save(owner,cid,rev,state)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(write,range(3)))
    for i,(owner,cid) in enumerate(keys):
        _,state=store.load(owner,cid)
        assert state['root_question']=='private-'+str(i) and state['user_facts']=={'test-marker':str(i)}
        assert state['system_hypotheses']==['hyp-'+str(i)]
        with pytest.raises(KeyError):store.load('b' if owner=='a' else 'a',cid)

def test_T25_known_followup_updates_only_selected_slot(tmp_path,monkeypatch):
    import kezohar.conversation_state as cs
    monkeypatch.setitem(cs.CASE_QUESTIONS,'rice',Q)
    store=memory(tmp_path);cid=store.create('a');a=MemoryAgent()
    store.turn(a,'a',cid,Q,circumstances=complete(tradition='sephardi'))
    r=store.turn(a,'a',cid,'TEST_FOLLOWUP',circumstances={'rice_form':'raw'})
    facts=store.load('a',cid)[1]['user_facts']
    assert facts=={'rice_form':'raw','tradition':'sephardi'}
    assert r['conversation']['memory_is_evidence'] is False
    assert a.calls[-1][1]['circumstances']==facts

def test_T26_unparsed_free_condition_not_silently_lost(tmp_path,monkeypatch):
    import kezohar.conversation_state as cs
    monkeypatch.setitem(cs.CASE_QUESTIONS,'rice',Q)
    store=memory(tmp_path);cid=store.create('a');a=MemoryAgent()
    root=Q+' PRIVATE_CASE_CONDITION_X'
    store.turn(a,'a',cid,root,circumstances=complete())
    store.turn(a,'a',cid,'TEST_EXPLICIT_CORRECTION',circumstances={'rice_form':'raw'})
    assert store.load('a',cid)[1]['user_facts']['rice_form']=='raw'
    r=store.turn(a,'a',cid,'TEST_FOLLOWUP UNKNOWN_CONDITION_Y',circumstances={'rice_form':'raw'})
    sent=a.calls[-1][0]
    assert r.get('mode')=='clarification' or ('PRIVATE_CASE_CONDITION_X' in sent and 'UNKNOWN_CONDITION_Y' in sent), 'free conditions discarded while recognized slot update permits answering'

def test_T27_concurrent_revision_compare_and_swap(tmp_path):
    store=memory(tmp_path);cid=store.create('a');rev,state=store.load('a',cid)
    def save(marker):
        try:store.save('a',cid,rev,dict(state,root_question=marker));return 'saved'
        except ConversationConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(save,['first','second']))
    assert sorted(out)==['conflict','saved'] and store.load('a',cid)[0]==1
    assert store.load('a',cid)[1]['root_question'] in ('first','second')

def test_T28_whole_turn_pruning_provenance_and_scoped_delete(tmp_path):
    store=memory(tmp_path,max_turns=2,max_chars=2000);cid=store.create('a');other=store.create('a')
    rev,state=store.load('a',cid)
    turns=[{'question':str(i)*400,'explicit_updates':{},'verdict':'test'} for i in range(4)]
    state.update(turns=turns,user_facts={'fact':'user'},system_hypotheses=['not-source-evidence'])
    store.save('a',cid,rev,state);saved=store.load('a',cid)[1]
    assert saved['turns']==turns[-2:] and saved['user_facts']=={'fact':'user'}
    assert saved['system_hypotheses']==['not-source-evidence']
    rev,saved=store.load('a',cid)
    larger=[dict(t,question=t['question']*3) for t in turns]
    saved['turns']=larger
    store.save('a',cid,rev,saved)
    pruned=store.load('a',cid)[1]
    assert len(json.dumps(pruned,ensure_ascii=False))<=2000
    assert pruned['turns']==larger[-1:]  # character limit prunes a whole turn
    assert not store.delete('b',cid) and store.delete('a',cid)
    with pytest.raises(KeyError):store.load('a',cid)
    assert store.load('a',other)[0]==0

def test_T29_normalization_expansion_does_not_mutate_source():
    from kezohar.discovery import interpret
    from kezohar.ranking import retrieval_query
    s=source();before=copy.deepcopy(s)
    text='בְּדִיקַת מקור שו״ע או״ח'
    hints=interpret(text);expanded=retrieval_query(text)
    assert 'שולחן ערוך' in hints['expansions'] and 'אורח חיים' in hints['expansions']
    assert 'בדיקת' in expanded and s==before

def make_db(tmp_path, items, name='library.sqlite3'):
    path=tmp_path/name
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE records(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        for s in items:db.execute('INSERT INTO records VALUES (?,?)',(s['source_id'],json.dumps(s,ensure_ascii=False)))
        rebuild_fts(db)
    return path

def test_T30_fts_core_terms_before_prefixes_and_refs_only_hints(tmp_path):
    from kezohar.ranking import retrieval_query
    from kezohar.discovery import interpret
    terms=['בדיקה'+chr(0x5d0+i) for i in range(20)]
    q=' '.join(terms)+' סימן אב סעיף ג'
    expanded=retrieval_query(q)
    assert all(normalize(t) in expanded.split()[:50] for t in terms)
    s=source(text=terms[-1]);db=make_db(tmp_path,[s])
    assert SQLiteLibrarySearch(db).search(expanded)[0]['source_id']=='s1'
    hints=interpret(q)['reference_hints']
    assert hints and all(h['status']=='query-hint-only' for h in hints)

def backend(items, **kw):
    return SimpleNamespace(bm25=SimpleNamespace(docs=[]),vector=None,revision='test',search=lambda *a,**k:copy.deepcopy(items),**kw)

def test_T31_rrf_dedup_and_collision_not_silently_replaced():
    a=source('a');b=source('b');c=source('c')
    f=FederatedSearch(backend([a,b]),[backend([c,a])])
    out=f.search('TEST_SEARCH')
    assert [s['source_id'] for s in out]==['a','c','b']  # c is first in its backend; b is second
    assert len({s['source_id'] for s in out})==3
    changed=source('a',text='CONFLICTING SYNTHETIC PAYLOAD')
    try:conflict=rrf_fuse([[a],[changed]])
    except ValueError:return
    assert not any(s['source_id']=='a' and not s.get('identity_conflict') for s in conflict), 'RRF silently keeps first payload for conflicting source ID'

def test_T32_backend_failure_has_explicit_status_and_deadline(monkeypatch):
    issues=[]
    def fail(*a,**kw):raise OSError('synthetic backend failure')
    bad=backend([]);bad.search=fail
    f=FederatedSearch(backend([source()]),[bad])
    try:
        r=f.search('TEST_SEARCH')
        if not (getattr(f,'errors',None) or isinstance(r,dict) and r.get('errors')):
            issues.append('missing structured partial-search status')
    except OSError:issues.append('backend exception escapes without structured partial-search status')
    # Already expired request: retrieval must not start. Virtual elapsed time
    # replaces a slow backend; no sleeping, physical I/O or performance claim.
    now=clock(monkeypatch);b=RequestBudget(seconds=1);now[0]=2;work=[]
    slow=backend([])
    def after_deadline(*args,**kwargs):
        work.append('backend-started-after-deadline');now[0]=3
        work.append('backend-completed-after-deadline');return [source()]
    slow.search=after_deadline
    a=agent();a.search=FederatedSearch(a.search,[slow])
    result=a.converse(Q,circumstances=complete(),request_budget=b)
    assert not a.answer_model.calls and result['verdict']=='budget_exhausted'
    if work:issues.append('retrieval starts/completes after expired budget: '+repr(work))
    assert not issues, '; '.join(issues)

def test_T33_embedding_namespace_changes_and_fts_survives(monkeypatch):
    spec=embeddings.VectorIndexSpec('fixture','fixed-vectors',2,'1')
    for change in [('dimensions',3),('revision','2'),('normalization','other'),('model','other')]:
        from dataclasses import replace
        new=replace(spec,**{change[0]:change[1]})
        assert new.namespace!=spec.namespace
        with pytest.raises(embeddings.VectorIndexMismatch):spec.check_manifest(new.manifest())
    class Vec:
        def search(self,*a,**kw):raise embeddings.VectorIndexMismatch('synthetic stale revision')
    h=HybridSearch([Source.from_dict(source())],vector_store=False);h.vector=Vec()
    assert h.search('בדיקת מקור') and h.vector_status=='reindex-required'

def test_T34_two_configured_fixed_providers_leave_corpus_and_vectors_unchanged(monkeypatch,tmp_path):
    # Constant fixture vectors, not an embedding/AI model.
    from kezohar.vector import MockVectorStore
    class ConstantVectors:
        spec=embeddings.VectorIndexSpec('fixture','constant',2,'1')
        def embed(self,text):return [1.0,0.0]
    vector=MockVectorStore(embedding_model=ConstantVectors())
    s=source();h=HybridSearch([Source.from_dict(s)],vector_store=vector)
    db=make_db(tmp_path,[s]);disk=SQLiteLibrarySearch(db)
    kb=KnowledgeBase(search_engine=FederatedSearch(h,[disk]))
    before=(db.read_bytes(),id(h.bm25),id(h.vector),copy.deepcopy(vector.vecs),vector.index_spec.namespace)
    monkeypatch.setitem(answer_models._PROVIDERS,'isolated-fixed',lambda settings:FixedAnswer(name=settings.model))
    a=Agent(knowledge=kb,answer_model=answer_models.ConfiguredAnswerModel())
    monkeypatch.setattr(api,'_agent',a)
    for name in ('fixed-a','fixed-b'):
        monkeypatch.setenv('LLM_MODEL',name)
        r=request('/ask',{'question':Q,'circumstances':complete()})
        stream=request('/ask',{'question':Q,'circumstances':complete(),'stream':True})
        assert r.status_code==stream.status_code==200 and r.json()['verdict']=='ok'
        assert a.answer_model.identity.model==name
    assert before==(db.read_bytes(),id(h.bm25),id(h.vector),vector.vecs,vector.index_spec.namespace)

def test_T35_graph_proposals_never_proof_review_needs_witness(tmp_path):
    g=HalachicSourceGraph(tmp_path/'graph.sqlite3');a,b=source('a'),source('b')
    eid=g.propose(a,b,'same-issue','synthetic similarity')
    with pytest.raises(ValueError):g.review(eid,[a,b],'test-reviewer','test rationale')
    r=g.relationships([a,b])[0]
    assert r['status']=='proposed' and not r['usable_as_claim_support'] and not r['halachic_verified']
    witnessed=g.propose(a,b,'cites','synthetic witness',quote=TEXT,witness=a)
    g.review(witnessed,[a,b],'test-reviewer','test rationale')
    assert all(not r['usable_as_claim_support'] for r in g.relationships([a,b]))

def test_T36_graph_changed_or_revoked_source_not_current_proof(tmp_path):
    g=HalachicSourceGraph(tmp_path/'graph.sqlite3');a,b=source('a'),source('b')
    eid=g.propose(a,b,'cites','test witness',quote=TEXT,witness=a)
    g.review(eid,[a,b],'reviewer','test rationale')
    changed=dict(a,text=TEXT+' changed')
    assert g.relationships([changed,b])[0]['status']=='stale-evidence'
    with pytest.raises(ValueError):g.review(eid,[changed,b],'reviewer','test')
    revoked=dict(a,metadata={'rag_answers_allowed':False})
    assert not g.relationships([revoked,b])

def test_T37_locator_requires_same_edition_full_proof_review_reversible(tmp_path):
    s=source(book_id=loc.BOOK_ID,metadata={'rag_answers_allowed':False,'locator_status':'ambiguous-file-fields',
        'file_sha256':'synthetic-file','text_sha256':hashlib.sha256(TEXT.encode()).hexdigest(),
        'original_rows':[1], 'heading':'בדיקה א-ב','topic':'בדיקה','siman':'א-ב','seif':'א',
        'seif_number':1,'original_locator_fields':[], 'locator_conflict':True,'opaque_numbering':True})
    db=make_db(tmp_path,[s]);original=db.read_bytes()
    diagnostics=hierarchy_diagnostics([s])
    assert diagnostics['s1'][0]['range_labels'][0]['assigns_individual_siman'] is False
    assert loc.build_queue(db)['auto_released']==0 and not loc.resolved_source(s)['metadata']['rag_answers_allowed']
    with pytest.raises(ValueError):loc.approve(db,'s1','catalog','anchor','reviewer','note')
    anchor={'anchor_id':'anchor','topic':'בדיקה','chapter_title':'בדיקה א-ב','siman':'א','seif':'א','text':TEXT,
            'source_url':'https://fixture.invalid/book/1/1'}
    catalog={'work_id':loc.BOOK_ID,'edition_id':'test-edition','anchors':[anchor]}
    path=tmp_path/'trusted.json';path.write_text(json.dumps(catalog,ensure_ascii=False))
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    registry={'resources':[{'id':'catalog','path':'trusted.json','work_id':loc.BOOK_ID,'sha256':sha,
        'approved':True,'reviewed_by':'fixture-reviewer','approved_hosts':['fixture.invalid'],
        'permission_evidence':'synthetic grant','scope':{p:True for p in ('local_storage','search_index','rag_answers')}}],
        'edition_bindings':[{'file_sha256':'synthetic-file','catalog_sha256':sha,'edition_id':'test-edition',
                            'verified':True,'reviewed_by':'fixture-reviewer','evidence':'synthetic binding'}]}
    loc.REGISTRY.write_text(json.dumps(registry))
    (tmp_path/'data').mkdir()
    (tmp_path/'data/yalkut_parquet_permission.json').write_text(json.dumps({'file_sha256':'synthetic-file',
        'verified':True,'evidence':'synthetic permission','scope':{p:True for p in ('local_storage','search_index','rag_answers')}}))
    loc.approve(db,'s1','catalog','anchor','fixture-reviewer','explicit synthetic review')
    assert loc.resolved_source(s)['metadata']['rag_answers_allowed'] and db.read_bytes()==original
    path.write_text('{}')
    assert not loc.resolved_source(s)['metadata']['rag_answers_allowed'] and db.read_bytes()==original

def test_T38_source_endpoint_status_collision_and_revoked_permission(monkeypatch,tmp_path):
    allowed=source('allowed');pending=source('pending',metadata={'rag_answers_allowed':False})
    ambiguous=source('ambiguous',metadata={'rag_answers_allowed':True,'locator_status':'ambiguous-file-fields'})
    a=agent([allowed,pending,ambiguous]);monkeypatch.setattr(api,'_agent',a)
    for sid,status in [('allowed',200),('missing',404),('pending',409),('ambiguous',409)]:
        r=request('/sources/'+sid,method='GET');assert r.status_code==status
        if status!=200:assert 'text' not in r.text
    db=make_db(tmp_path,[source('allowed',text='collision fixture')])
    a.search=FederatedSearch(a.search,[SQLiteLibrarySearch(db)])
    assert request('/sources/allowed',method='GET').status_code==404
    # Fresh hydration sees permission withdrawal in the current source record.
    a=agent([source('allowed',metadata={'rag_answers_allowed':False})]);monkeypatch.setattr(api,'_agent',a)
    assert request('/sources/allowed',method='GET').status_code==409
    # Same locator/text across stores, but inconsistent current permissions:
    # an allowed first payload must not hide a blocked matching record.
    blocked=source('same',metadata={'rag_answers_allowed':False})
    db2=make_db(tmp_path,[blocked],name='revoked.sqlite3')
    a=agent([source('same')]);a.search=FederatedSearch(a.search,[SQLiteLibrarySearch(db2)])
    monkeypatch.setattr(api,'_agent',a)
    r=request('/sources/same',method='GET')
    assert r.status_code in (404,409) and TEXT not in r.text, 'source endpoint exposes text when first duplicate is allowed but matching record is revoked'

def fallback(monkeypatch,path,body):
    import http.server
    holder={}
    class NoServer:
        def __init__(self,address,handler):holder['handler']=handler
        def serve_forever(self):pass
    monkeypatch.setattr(http.server,'HTTPServer',NoServer)
    api.run_stdio_fallback(port=9999)  # constructor is a stub, no bind/listen
    h=object.__new__(holder['handler']);raw=json.dumps(body).encode()
    h.headers={'Content-Length':str(len(raw))};h.rfile=io.BytesIO(raw);h.path=path;out=[]
    h._send=lambda code,obj,*a:out.append((code,obj))
    h.do_POST()
    return out[0]

def test_T39_invalid_json_types_and_fastapi_fallback_parity(monkeypatch):
    a=agent();monkeypatch.setattr(api,'_agent',a);errors=[]
    cases=[('/ask',{'question':17}),('/ask',{'question':['TEST']}),('/ask',{'question':Q,'top_k':{}}),
           ('/ask',{'question':Q,'circumstances':{'unsupported':'x'}}),('/ask',{}),
           ('/search',[]),('/search',{'query':17}),('/search',{'query':'TEST','top_k':'bad'})]
    for path,body in cases:
        for kind in ('fastapi','fallback'):
            try:
                status=request(path,body).status_code if kind=='fastapi' else fallback(monkeypatch,path,body)[0]
                if status not in (400,422):errors.append((kind,path,repr(body),'status '+str(status)))
            except (AttributeError,TypeError,ValueError) as exc:
                errors.append((kind,path,repr(body),type(exc).__name__))
    assert not a.answer_model.calls
    assert not errors,'malformed input not rejected consistently: '+repr(errors)

def test_T40_sse_order_layers_graph_and_rejected_claim_hidden(monkeypatch,tmp_path):
    a=agent(model=FixedAnswer(output=claim(source(),'UNSUPPORTED_SYNTHETIC_CLAIM')))
    monkeypatch.setattr(api,'_agent',a)
    stream=api._stream_local(Q,circumstances=complete())
    first=next(stream)
    assert first.startswith('event: sources') and not a.answer_model.calls
    rest=''.join(stream);ev=events(first+rest);done=ev[-1][1]
    assert ev[-1][0]=='done' and len(a.answer_model.calls)==1
    assert done['verification_layers'] and done['halachic_verified'] is False
    assert 'source_relationships' in done and 'UNSUPPORTED_SYNTHETIC_CLAIM' not in rest
    assert done['structured_answer']['sources']==[]
    proposal={'status':'proposed','usable_as_claim_support':False}
    composed=VerifiedAnswerComposer().compose({'answer':'fixture','sources':[],'source_relationships':[proposal]})
    assert events(''.join(api._sse_events(composed)))[-1][1]['source_relationships']==[proposal]
    s=source();install_catalog(tmp_path,s)
    verified=ExtractiveSourceVerifier().verify(Q,claim(s),[s])
    assert verified['verdict']=='ok'
    revoked=dict(s,metadata={'rag_answers_allowed':False})
    composed=VerifiedAnswerComposer().compose({'answer':CLAIM,'sources':[revoked],
        'verification':verified,'verdict':'ok','mode':'llm'})
    assert composed['verdict']=='invalid_citation' and not composed['structured_answer']['sources']
    assert composed['verification_layers']['claim_support']['status']!='supported-bounded', 'blocked snapshot still advertises supported-bounded in verification layers'
