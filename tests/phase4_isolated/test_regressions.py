"""Synthetic adversarial regression cases for the eight phase-4 fixes."""
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_contracts import (sandbox, source, agent, FixedAnswer, Q, TEXT, CLAIM,
    complete, quote, claim, request, events, clock, install_catalog, memory,
    MemoryAgent, make_db, backend, fallback)
from kezohar import api, semantic_claims, answer_models
from kezohar.hybrid import SearchResults, HybridSearch, FederatedSearch, rrf_fuse
from kezohar.models import Source
from kezohar.knowledge import KnowledgeBase
from kezohar.verification import ExtractiveSourceVerifier
from kezohar.answer_composition import VerifiedAnswerComposer
from kezohar.request_budget import RequestBudget, BudgetExceeded
from kezohar.library_search import SQLiteLibrarySearch
from kezohar.source_snapshot import fingerprint


@pytest.mark.parametrize('protocol',['json','legacy'])
def test_quote_cannot_skip_preceding_or_following_condition(protocol):
    s=source(text='רק אם דגל בדיקה פעיל, מציגים סמל אלפא. אין להציגו כשהדגל כבוי.')
    v=ExtractiveSourceVerifier()
    def output(text):
        return json.dumps({'quotes':[{'source_id':'s1','quote':text}]}) if protocol=='json' else '״'+text+'״ ('+s['reference']+').'
    assert v.verify('סמל אלפא',output(s['text']),[s])['verdict']=='ok'
    for partial in ('מציגים סמל אלפא.','רק אם דגל בדיקה פעיל, מציגים סמל אלפא.'):
        assert v.verify('סמל אלפא',output(partial),[s])['verdict']!='ok'

@pytest.mark.parametrize('change',[{'version':''},{'version':'edition-two'},{'author':'another author'},
                                  {'source_id':'alias'}, {'metadata':{'rag_answers_allowed':False}},
                                  {'metadata':{'locator_status':'ambiguous-file-fields'}}])
def test_claim_unit_requires_current_edition_identity_and_permissions(tmp_path,change):
    s=source();install_catalog(tmp_path,s);v=ExtractiveSourceVerifier()
    assert v.verify(Q,claim(s),[s])['verdict']=='ok'
    changed=dict(s,**change)
    assert v.verify(Q,claim(changed),[changed])['verdict']!='ok'

def test_legacy_unversioned_and_duplicate_evidence_units_fail_closed(tmp_path):
    s=source();rule=install_catalog(tmp_path,s);path=tmp_path/'catalog.json'
    unversioned=dict(rule);unversioned.pop('version')
    path.write_text(json.dumps({'rules':[unversioned]}))
    assert semantic_claims.units_for(Q,s)==[]
    path.write_text(json.dumps({'rules':[rule,dict(rule,variants=['UNREVIEWED'])]}))
    assert ExtractiveSourceVerifier().verify(Q,claim(s),[s])['verdict']!='ok'

def test_snapshot_changes_invalidate_display_even_for_exact_same_quote(tmp_path):
    s=source();install_catalog(tmp_path,s)
    v=ExtractiveSourceVerifier().verify(Q,claim(s),[s])
    for field,value in [('version','changed'),('author','changed'),('reference','changed'),
                        ('metadata',{'rag_answers_allowed':True,'permission_revision':'changed'})]:
        changed=dict(s,**{field:value})
        r=VerifiedAnswerComposer().compose({'answer':CLAIM,'verdict':'ok','mode':'llm','verification':v,'sources':[changed]})
        assert r['verdict']=='invalid_citation' and r['structured_answer']['explanations']==[]
        assert r['verification_layers']['overall']=='not-approved'
        assert r['verification_layers']['claim_support']['status']!='supported-bounded'
        assert r['verification_layers']['permissions']=='not-proved'
        assert not r['halachic_verified']
        assert CLAIM not in json.dumps(r,ensure_ascii=False)
        assert 'evidence' not in r['verification'] and 'claims' not in r['verification']

@pytest.mark.parametrize('field',['tradition','authority_level','category','source_file','section','normalized_text'])
def test_other_stored_source_fields_are_part_of_snapshot_identity(field):
    s=source();changed=dict(s,**{field:'changed-synthetic-metadata'})
    assert fingerprint(s)!=fingerprint(changed)

def test_catalog_change_invalidates_display_and_cached_answer(tmp_path):
    s=source();install_catalog(tmp_path,s);a=agent(model=FixedAnswer(output=claim(s)))
    first=a.ask(Q);assert first['verdict']=='ok'
    assert a.ask(Q).get('cached') and len(a.answer_model.calls)==1
    (tmp_path/'catalog.json').write_text(json.dumps({'rules':[]}))
    displayed=VerifiedAnswerComposer().compose(first)
    assert displayed['verdict']=='invalid_citation'
    again=a.ask(Q)
    assert again['verdict']=='review_required' and not again.get('cached') and len(a.answer_model.calls)==2

@pytest.mark.parametrize('change',[{'version':'changed'},{'text':TEXT+' נוסף'},
                                  {'metadata':{'rag_answers_allowed':False}},
                                  {'metadata':{'rag_answers_allowed':True,'permission_revision':'new'}}])
def test_generation_cannot_use_snapshot_changed_during_call(change):
    a=agent()
    def mutate():
        original=a.search.bm25.docs[0]
        for k,v in change.items():setattr(original,k,v)
    a.answer_model.hook=mutate
    r=a.converse(Q,circumstances=complete(),retrieved_sources=[source()])
    assert r['verdict']=='invalid_citation' and not r['structured_answer']['sources']
    assert CLAIM not in r['answer'] and not r['halachic_verified']

def test_revoked_permission_invalidates_cached_source_answer():
    a=agent();first=a.ask('בדיקת מקור סינתטי');assert first['verdict']=='ok'
    assert a.ask('בדיקת מקור סינתטי').get('cached')
    a.search.bm25.docs[0].metadata={'rag_answers_allowed':False}
    again=a.ask('בדיקת מקור סינתטי')
    assert again['verdict']=='rag-scope-pending' and not again.get('cached')
    assert len(a.answer_model.calls)==1

def test_rejected_cached_answer_cannot_expose_newly_revoked_sources():
    a=agent(model=FixedAnswer(output='UNSUPPORTED OUTPUT'))
    first=a.ask('בדיקת מקור סינתטי')
    assert first['mode']=='llm-guarded'
    a.search.bm25.docs[0].metadata={'rag_answers_allowed':False}
    again=a.ask('בדיקת מקור סינתטי')
    assert again['verdict']=='rag-scope-pending' and not again.get('cached')

def test_empty_answer_cache_invalidated_by_corpus_update():
    a=agent([source(text='UNRELATED SYNTHETIC TEXT')])
    assert a.ask('בדיקת מקור סינתטי')['verdict']=='no_source'
    a.search.bm25.add([Source.from_dict(source('new'))])
    assert a.ask('בדיקת מקור סינתטי')['verdict']=='ok'

def test_free_conditions_survive_unrecognized_turns_and_history_pruning(tmp_path,monkeypatch):
    import kezohar.conversation_state as cs
    monkeypatch.setitem(cs.CASE_QUESTIONS,'rice',Q)
    store=memory(tmp_path,max_turns=1);cid=store.create('a');a=MemoryAgent()
    store.turn(a,'a',cid,Q+' ORIGINAL_FREE_CONDITION',circumstances=complete())
    no_slot=store.turn(a,'a',cid,'UNPARSED_FOLLOWUP_CONDITION')
    assert no_slot['verdict']=='test-only' and not no_slot['halachic_verified']
    assert len(a.calls)==2 and 'UNPARSED_FOLLOWUP_CONDITION' in a.calls[-1][0]
    assert a.calls[-1][1]['circumstances']=={'rice_form':'cooked'}
    store.turn(a,'a',cid,'LATEST_FREE_CONDITION',circumstances={'rice_form':'raw'})
    sent=a.calls[-1][0]
    assert all(x in sent for x in ('ORIGINAL_FREE_CONDITION','UNPARSED_FOLLOWUP_CONDITION','LATEST_FREE_CONDITION'))
    state=store.load('a',cid)[1]
    assert len(state['turns'])==1 and len(state['free_conditions'])==2
    assert state['user_facts']=={'rice_form':'raw'}

def test_conflicting_original_wording_and_updated_slot_require_clarification(tmp_path):
    a=agent();store=memory(tmp_path);cid=store.create('a')
    store.turn(a,'a',cid,Q+' לא מבושל',circumstances={'rice_form':'raw'})
    count=len(a.answer_model.calls)
    r=store.turn(a,'a',cid,'TEST_CORRECTION',circumstances=complete())
    assert r['mode']=='rule-with-clarification' and len(a.answer_model.calls)==count+1
    assert len(r['clarifications'])==1 and not r['answer_policy']['personal_ruling_verified']
    assert store.load('a',cid)[1]['root_question']==Q+' לא מבושל'

@pytest.mark.parametrize('changed',[{'text':'different text'},{'version':'other'},
                                  {'author':'other'}, {'metadata':{'rag_answers_allowed':False}}])
def test_conflict_is_order_independent_and_never_exposes_either_text(changed):
    a=source();b=dict(a,**changed)
    for lists in ([[a],[b]],[[b],[a]],[[a,b]]):
        result=rrf_fuse(lists)
        assert result==[] and result.status['partial']
        assert result.errors[0]['error']=='conflicting-source-snapshots'

def test_single_backend_conflicts_are_not_lost_by_bm25_deduplication(monkeypatch):
    a=agent([source(),source(text=TEXT+' different')]);monkeypatch.setattr(api,'_agent',a)
    r=request('/ask',{'question':Q,'circumstances':complete()}).json()
    assert r['verdict']=='partial_search' and r['search_status']['partial']
    assert r['sources']==[] and not a.answer_model.calls
    assert request('/sources/s1',method='GET').status_code==404

def test_nested_identity_error_cannot_be_hidden_by_other_backend():
    a=source();h=HybridSearch([Source.from_dict(a),Source.from_dict(source(text=TEXT+' conflict'))],vector_store=False)
    f=FederatedSearch(h,[backend([a])])
    results=f.search('בדיקת מקור סינתטי')
    assert results==[] and results.status['partial']

def test_partial_search_visible_in_json_sse_and_no_source_admission(monkeypatch):
    bad=backend([])
    def fail(*a,**kw):raise OSError('synthetic unavailable backend')
    bad.search=fail
    a=agent();a.search=FederatedSearch(a.search,[bad]);monkeypatch.setattr(api,'_agent',a)
    body={'question':Q,'circumstances':complete()}
    normal=request('/ask',body).json()
    stream=events(request('/ask',dict(body,stream=True)).text)
    done=stream[-1][1]
    assert normal['verdict']==done['verdict']=='partial_search'
    assert normal['search_status']==done['search_status'] and done['search_status']['partial']
    assert stream[0][1]['search_status']['partial'] and not a.answer_model.calls
    assert not done['halachic_verified'] and done['structured_answer']['sources']==[]

def test_empty_partial_search_is_not_no_source_or_cached():
    a=agent();a.search=backend(SearchResults([], [{'error':'synthetic backend failure'}]))
    r=a.ask(Q)
    assert r['verdict']=='partial_search' and not a._cache and not a.answer_model.calls

def test_deadline_after_primary_stops_new_work_and_rejects_late_sources(monkeypatch):
    now=clock(monkeypatch);b=RequestBudget(seconds=1);calls=[]
    a=agent()
    def expired_search(*args,**kwargs):
        calls.append('search');now[0]=2;return [source()]
    a.search=backend([]);a.search.search=expired_search
    r=a.converse(Q,circumstances=complete(),request_budget=b)
    assert calls==['search'] and r['verdict']=='budget_exhausted'
    assert r['sources']==[] and not a.answer_model.calls

def test_supported_sqlite_backend_rejects_before_opening_database(tmp_path,monkeypatch):
    now=clock(monkeypatch);db=make_db(tmp_path,[source()]);b=RequestBudget(seconds=1);now[0]=2
    import sqlite3
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**kw:pytest.fail('database opened after deadline'))
    with pytest.raises(BudgetExceeded):SQLiteLibrarySearch(db).search('TEST_SEARCH',request_budget=b)

def test_no_new_web_fetch_after_virtual_deadline(monkeypatch):
    from kezohar.web_research import WebResearchEngine
    now=clock(monkeypatch);b=RequestBudget(seconds=1);calls=[]
    class Search:
        def search(self,*a,**kw):return ['https://fixture.invalid/a','https://fixture.invalid/b']
    def fetch(url,request_budget=None):
        calls.append(url);now[0]=2
        return '<title>הלכות בדיקה</title><p>בדיקת מקור סינתטי בלבד.</p>',url
    engine=WebResearchEngine(searcher=Search(),fetcher=fetch,sites={'fixture.invalid':{}},licenses={})
    a=agent();a.research_engine=engine
    r=a.converse(Q,circumstances=complete(),research=True,request_budget=b)
    assert calls==['https://fixture.invalid/a'] and not a.answer_model.calls
    assert r['verdict']=='budget_exhausted' and r['search_status']['partial']

def test_expired_research_does_not_call_searcher_or_fetcher(monkeypatch):
    from kezohar.web_research import WebResearchEngine
    now=clock(monkeypatch);b=RequestBudget(seconds=1);now[0]=2
    class NoSearch:
        def search(self,*a,**kw):pytest.fail('web search after deadline')
    engine=WebResearchEngine(searcher=NoSearch(),fetcher=lambda *a,**kw:pytest.fail('fetch after deadline'),sites={},licenses={})
    r=engine.research('TEST_CASE',request_budget=b)
    assert r['errors'] and r['sources']==[] and b.reason

def test_expired_generation_does_not_prepare_prompt(monkeypatch):
    from kezohar.request_budget import BudgetedAnswerModel
    now=clock(monkeypatch);b=RequestBudget(seconds=1);now[0]=2
    monkeypatch.setattr('kezohar.request_budget.build_messages',lambda *a,**kw:pytest.fail('prompt after deadline'))
    m=FixedAnswer()
    with pytest.raises(BudgetExceeded):BudgetedAnswerModel(m,b).generate(Q,[source()])
    assert not m.calls

def test_source_revalidation_stops_before_next_lookup_after_deadline(monkeypatch):
    from kezohar.request_budget import revalidate_sources
    now=clock(monkeypatch);b=RequestBudget(seconds=1);calls=[]
    def resolve(sid,request_budget=None):
        calls.append(sid);now[0]=2;return source(sid)
    with pytest.raises(BudgetExceeded):revalidate_sources([source('one'),source('two')],resolve,b)
    assert calls==['one']

def test_expired_sqlite_lookup_does_not_open_database(tmp_path,monkeypatch):
    now=clock(monkeypatch);path=make_db(tmp_path,[source()]);b=RequestBudget(seconds=1);now[0]=2
    import sqlite3
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k:pytest.fail('lookup opened database after deadline'))
    with pytest.raises(BudgetExceeded):SQLiteLibrarySearch(path).source_by_id('s1',request_budget=b)

@pytest.mark.parametrize('path',['/ask','/research','/search'])
@pytest.mark.parametrize('raw',[b'{bad',b'[]',b'{"question":"A","question":"B"}',b'{"query":NaN}'])
def test_invalid_json_rejected_before_agent_creation(monkeypatch,path,raw):
    monkeypatch.setattr(api,'get_agent',lambda:pytest.fail('invalid input reached agent'))
    r=request(path,raw=raw)
    assert r.status_code==400 and not r.json()['halachic_verified']

@pytest.mark.parametrize('field,value',[('top_k',True),('top_k',1.5),('top_k',0),('stream','true'),
                                       ('research',1),('lat','31'),('lon',181),('location',[]),
                                       ('circumstances',[])])
def test_invalid_options_json_sse_and_fallback_have_same_rejection(monkeypatch,field,value):
    monkeypatch.setattr(api,'get_agent',lambda:pytest.fail('invalid options reached agent'))
    body={'question':Q,'circumstances':complete(),'stream':True,field:value}
    r=request('/ask',body)
    status,result=fallback(monkeypatch,'/ask',body)
    assert r.status_code==status==400 and r.json()==result

def test_pending_sources_redacted_in_search_normal_answer_and_sse(monkeypatch):
    a=agent([source(metadata={'rag_answers_allowed':False})]);monkeypatch.setattr(api,'_agent',a)
    for path,body in [('/search',{'query':'בדיקת מקור'}),('/ask',{'question':Q,'circumstances':complete()}),
                      ('/ask',{'question':Q,'circumstances':complete(),'stream':True})]:
        response=request(path,body)
        assert response.status_code==200 and TEXT not in response.text
    assert not a.answer_model.calls

def test_sse_and_json_agree_after_permission_changes_during_generation(monkeypatch):
    for stream in (False,True):
        a=agent();monkeypatch.setattr(api,'_agent',a)
        a.answer_model.hook=lambda:a.search.bm25.docs[0].metadata.update(rag_answers_allowed=False)
        r=request('/ask',{'question':Q,'circumstances':complete(),'stream':stream})
        result=events(r.text)[-1][1] if stream else r.json()
        assert result['verdict']=='invalid_citation' and not result['structured_answer']['sources']
        assert result['verification_layers']['overall']=='not-approved' and not result['halachic_verified']

def test_sse_revalidates_permissions_between_sources_event_and_generation(monkeypatch):
    a=agent();monkeypatch.setattr(api,'_agent',a)
    stream=api._stream_local(Q,circumstances=complete())
    assert next(stream).startswith('event: sources')
    a.search.bm25.docs[0].metadata['rag_answers_allowed']=False
    remaining=''.join(stream);result=events(remaining)[-1][1]
    assert result['verdict']=='invalid_citation' and not a.answer_model.calls
    assert not result['structured_answer']['sources'] and TEXT not in remaining

def test_rejected_claim_not_leaked_via_verification_diagnostics(tmp_path,monkeypatch):
    s=source();install_catalog(tmp_path,s)
    for stream in (False,True):
        a=agent(model=FixedAnswer(output=claim(s,'UNSUPPORTED_DIAGNOSTIC_CLAIM')))
        monkeypatch.setattr(api,'_agent',a)
        r=request('/ask',{'question':Q,'circumstances':complete(),'stream':stream})
        assert 'UNSUPPORTED_DIAGNOSTIC_CLAIM' not in r.text
        result=events(r.text)[-1][1] if stream else r.json()
        assert result['verdict']=='review_required' and not result['structured_answer']['explanations']

def test_revoked_source_not_leaked_via_reasoning_diagnostics(tmp_path,monkeypatch):
    s=source();install_catalog(tmp_path,s)
    a=agent(model=FixedAnswer(output=claim(s)));monkeypatch.setattr(api,'_agent',a)
    a.answer_model.hook=lambda:a.search.bm25.docs[0].metadata.update(rag_answers_allowed=False)
    r=request('/ask',{'question':Q,'circumstances':complete()})
    result=r.json()
    assert result['verdict']=='invalid_citation' and TEXT not in r.text
    assert result['reasoning']['supported_statement_units']==[]

def test_dropped_source_regression_uses_real_synthetic_corpus_membership():
    small=source();big=source('big',text=TEXT*1000)
    a=agent([small,big],model=FixedAnswer(output=quote(big)))
    r=a.converse(Q,circumstances=complete(),retrieved_sources=[small,big],
                 request_budget=RequestBudget(max_context_bytes=6000))
    assert len(a.answer_model.calls)==1 and r['verdict']=='invalid_citation'
    assert [s['source_id'] for s in a.answer_model.calls[0][1]]==['s1']
    assert r['orchestration']['budget']['dropped_source_ids']==['big']

def test_unknown_or_stale_supplied_source_blocked_before_generation():
    a=agent()
    r=a.converse(Q,circumstances=complete(),retrieved_sources=[source(version='stale')])
    assert r['verdict']=='invalid_citation' and not a.answer_model.calls

def test_oversized_preserved_memory_fails_without_silent_truncation(tmp_path):
    store=memory(tmp_path,max_chars=2000);cid=store.create('a');a=MemoryAgent()
    store.turn(a,'a',cid,Q,circumstances=complete())
    before=store.load('a',cid)
    with pytest.raises(ValueError):store.turn(a,'a',cid,'FREE_CONDITION_'*140)
    assert store.load('a',cid)==before

def test_federated_error_diagnostics_are_thread_local():
    def search(q,**kw):
        if q=='TEST_FAIL':raise OSError('test')
        return [source()]
    b=backend([]);b.search=search
    f=FederatedSearch(backend([source()]),[b]);barrier=threading.Barrier(2)
    def run(q):
        result=f.search(q);barrier.wait(timeout=2)
        return result.status,copy.deepcopy(f.errors)
    with ThreadPoolExecutor(max_workers=2) as pool:
        failure=pool.submit(run,'TEST_FAIL');success=pool.submit(run,'TEST_OK')
        failed,errors=failure.result();passed,no_errors=success.result()
    assert failed['partial'] and errors and not passed['partial'] and not no_errors
