import sys
sys.path.insert(0, "src")
from kezohar import agent as A
from kezohar import ingest

def _agent_no_llm():
    import json
    raws = json.loads(open("data/sample_sources/sources.json", encoding="utf-8").read())
    lic = ingest.load_licenses()
    srcs = []
    for r in raws:
        s, e = ingest.prepare_source(r, lic)
        srcs.extend(s)
    # base_url empty -> sources-only fallback
    return A.Agent(sources=srcs, base_url="", model="test")

def test_fastpath_via_agent():
    ag = _agent_no_llm()
    r = ag.ask("מתי שקיעה היום בנתיבות?")
    assert r["mode"] == "fast" and r["elapsed_s"] < 1.0

def test_out_of_scope():
    ag = _agent_no_llm()
    r = ag.ask("מה מזג האוויר מחר?")
    assert r["verdict"] == "out_of_scope"

def test_sources_only_when_llm_down():
    ag = _agent_no_llm()
    r = ag.ask("מה מברכים על אורז?")
    assert r["mode"] == "sources-only" and r["sources"]

def test_no_source_when_empty_store():
    ag = A.Agent(sources=[], base_url="")
    r = ag.ask("מה מברכים על אורז?")
    assert r["verdict"] == "no_source" and r["answer"] == "אין לי מקור לכך."

def test_cache():
    ag = _agent_no_llm()
    r1 = ag.ask("מה מברכים על אורז?")
    r2 = ag.ask("מה מברכים על אורז?")
    assert r2.get("cached") is True

def test_empty_question():
    ag = _agent_no_llm()
    r = ag.ask("   ")
    assert r["verdict"] == "empty"

def test_sephardi_first():
    ag = _agent_no_llm()
    res = ag.search_only("בשר גבינה", top_k=5)
    assert res  # ordering stable; tradition field present
    assert all("tradition" in s for s in res)

def test_local_answer_support_guard_rejects_inverted_claim(monkeypatch):
    from kezohar import llm
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':'אסור לאכול אורז (שולחן ערוך, אורח חיים רח:ז).'})
    ag=_agent_no_llm();result=ag.ask('מה מברכים על אורז?')
    assert result['mode']=='llm-guarded' and result['verdict']=='unsupported'

def test_generic_terms_and_prefix_substring_are_not_evidence():
    from kezohar.ranking import retrieval_query, topic_overlap
    assert 'אורז' in retrieval_query('מה מברכים על אורז?').split()
    assert 'מברכימ' not in retrieval_query('מה מברכים על אורז?').split()
    assert topic_overlap('מברכים על אור ביום כיפור','מה מברכים על אורז?')==0
    assert topic_overlap('הכוסס את האורז','מה מברכים על אורז?')==1
    assert A.order_sources([{'work_title':'קיצור שולחן ערוך','text':'אורז','score':1}], 'אורז')[0]['halachic_authority']=='ashkenazi-posek'

def test_search_only_grant_never_reaches_llm(monkeypatch):
    from kezohar.models import Source
    from kezohar import llm
    def forbidden(*a,**k):raise AssertionError('RAG scope not authorized')
    monkeypatch.setattr(llm,'ask',forbidden)
    s=Source(source_id='index-only',work_title='ספר',reference='א:א',text='אורז מזונות',metadata={'rag_answers_allowed':False})
    ag=A.Agent(sources=[s],base_url='local')
    assert ag.search_only('אורז')
    result=ag.ask('ברכת אורז')
    assert result['mode']=='sources-only' and result['verdict']=='rag-scope-pending'

def test_search_permission_revision_invalidates_cached_answer(monkeypatch):
    from kezohar.models import Source
    from kezohar import llm
    s=Source(source_id='changing-scope',work_title='ספר',reference='א:א',text='אורז מזונות')
    ag=A.Agent(sources=[s],base_url='local')
    class ChangingSearch:
        revision=1
        def search(self,*a,**k):return [s.to_dict()]
    ag.search=ChangingSearch()
    monkeypatch.setattr(llm,'ask',lambda *a,**k:{'answer':'״אורז מזונות״ (א:א).'})
    assert ag.ask('ברכת אורז')['mode']=='llm'
    assert ag.ask('ברכת אורז')['cached']
    s.metadata['rag_answers_allowed']=False;ag.search.revision=2
    r=ag.ask('ברכת אורז')
    assert r['verdict']=='rag-scope-pending' and not r.get('cached')
