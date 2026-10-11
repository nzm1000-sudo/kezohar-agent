"""Agent orchestration: fastpath -> retrieval (code) -> one LLM call -> safety check."""
import time
from . import fastpath, llm as llm_client
from .knowledge import KnowledgeBase
from .answer_models import ConfiguredAnswerModel
from .verification import ExtractiveSourceVerifier
from .ranking import topic_tokens, retrieval_query, topic_overlap
from .permissions import rag_eligible
from . import evidence
from .source_quality import classify, exclusion_reason
from .halachic_authority import profile as authority_profile, selection_key
from .question_understanding import analyze, case_coverage
from .source_snapshot import fingerprint
from .hybrid import SearchResults
from .semantic_claims import catalog_revision


def diverse_sources(ordered, limit):
    """Keep relevant authority order while avoiding one work filling the prompt.

    This changes selection only, never text/locator or evidence approval.
    Distinct excerpts/editions stay separate records, including on the second pass.
    """
    if limit<1:return []
    chosen=[];works=set();ids=set()
    for source in ordered:
        work=(source.get('work_title'),source.get('author'),source.get('tradition'))
        if work in works or source['source_id'] in ids:continue
        chosen.append(source);works.add(work);ids.add(source['source_id'])
        if len(chosen)>=limit:return chosen
    for source in ordered:
        if source['source_id'] not in ids:
            chosen.append(source);ids.add(source['source_id'])
            if len(chosen)>=limit:break
    return chosen

def order_sources(sources, question=""):
    """Maran/Sephardi first, then others — stable within groups."""
    sources = [s for s in sources if not exclusion_reason(question, s)]
    if question:
        terms = topic_tokens(question)
        if terms:
            sources = [s for s in sources if topic_overlap(s.get('text',''),question)>0]
    for source in sources:
        source.update(classify(source))
        source['topical_overlap'] = topic_overlap(source.get('text',''),question) if question else 0
        source.setdefault('search_relevance', source.get('score',0))
        source.setdefault('source_reliability', source.get('metadata',{}).get('source_reliability','import-provenance-only'))
        source.setdefault('halachic_authority', source.get('authority_level','') or ('maran' if source.get('work_title','').startswith('שולחן ערוך') or source.get('book_id')=='Beit_Yosef' else 'unclassified'))
        source.setdefault('evidence_support', 'not-claim-verified')
        source['authority_profile']=authority_profile(source)
        source['halachic_authority']=source['authority_profile']['authority']
        source['retrieval_tradition']=source['authority_profile']['tradition']
        source['case_coverage']=case_coverage(question,source) if question else 0
    preferred=analyze(question)['circumstances']['tradition'] if question else 'sephardi'
    for source in sources:
        source['_selection_key']=selection_key(source,question,preferred)
    return sorted(sources, key=lambda s: (
        not rag_eligible(s),
        s['_selection_key']))


class Agent:
    def __init__(self, sources=None, store_path=None, base_url=None, model=None, research_engine=None,
                 knowledge=None, search_engine=None, answer_model=None, source_verifier=None, source_graph=None):
        self.knowledge = knowledge if knowledge is not None else KnowledgeBase(sources, store_path, search_engine)
        self.answer_model = answer_model if answer_model is not None else ConfiguredAnswerModel(base_url, model)
        self.source_verifier = source_verifier if source_verifier is not None else ExtractiveSourceVerifier()
        self.research_engine = research_engine
        self.source_graph = source_graph
        self._cache_revision = None
        self._cache = {}

    @property
    def base_url(self):
        return getattr(self.answer_model.identity, 'base_url', '')

    @property
    def model(self):
        return getattr(self.answer_model.identity, 'model', '')

    @property
    def search(self):
        return self.knowledge.search

    @search.setter
    def search(self, value):
        self.knowledge.search = value

    def ask(self, question, top_k=5, lat=None, lon=None, location=None, timeout=4.5, cache_ttl=300, retrieved_sources=None, answer_model=None):
        t0 = time.time()
        q = (question or "").strip()
        cacheable = answer_model is None and retrieved_sources is None
        if not q:
            return {"answer": "נא לשאול שאלה.", "sources": [], "verdict": "empty",
                    "mode": "refuse", "elapsed_s": 0.0}
        # Permission/index changes invalidate answers derived from older records.
        revision = (getattr(self.search,"revision",None), self.answer_model.identity,catalog_revision())
        if revision != self._cache_revision:
            self._cache.clear()
            self._cache_revision = revision
        # cache
        now = time.time()
        if q in self._cache and cacheable:
            ts, res = self._cache[q]
            if now - ts < cache_ttl:
                pinned={s['source_id']:fingerprint(s) for s in res.get('sources',[])}
                unchanged=all((current:=self.knowledge.source_by_id(sid)) is not None
                              and fingerprint(current)==digest for sid,digest in pinned.items())
                if unchanged:
                    r = dict(res)
                    r["cached"] = True
                    return r
                self._cache.pop(q,None)
        # out of scope -> polite refusal (no retrieval needed, but include empty sources)
        if fastpath.is_out_of_scope(q):
            res = {"answer": "מצטער, אני עונה רק על הלכה, מנהגים, ברכות, זמנים, תפילות, צומות, שבת, חגים ולוח השנה העברי.",
                   "sources": [], "verdict": "out_of_scope", "mode": "refuse",
                   "elapsed_s": round(time.time() - t0, 3)}
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        # fast path (zmanim/calendar) — no LLM
        fp = fastpath.handle(q, lat=lat or fastpath.DEFAULT_LAT, lon=lon or fastpath.DEFAULT_LON,
                             location=location or fastpath.DEFAULT_LOCATION)
        if fp is not None:
            res = {"answer": fp["answer"], "sources": [], "verdict": fp["kind"],
                   "mode": "fast", "details": fp, "elapsed_s": round(time.time() - t0, 3)}
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        # retrieval first (in code)
        retrieved = retrieved_sources if retrieved_sources is not None else self.search_only(q,top_k=top_k)
        search_status=getattr(retrieved,'status',{'partial':False,'errors':[]})
        if search_status['partial']:
            return {'answer':'החיפוש הושלם באופן חלקי; אין בסיס לתשובה מאומתת.',
                    'sources':retrieved,'search_status':search_status,'verdict':'partial_search',
                    'mode':'sources-only','human_review':'required','halachic_verified':False}
        if not retrieved:
            res = {"answer": evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else "אין לי מקור לכך.", "sources": [],
                   "verdict": "no_source", "mode": "sources-only",
                   "elapsed_s": round(time.time() - t0, 3)}
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        searchable = retrieved
        retrieved = [s for s in retrieved if rag_eligible(s)]
        if not retrieved:
            return {'answer':'מצב חיפוש: המקורות מותרים לחיפוש; היקף השימוש בהם להפקת תשובה עדיין בבירור.',
                    'sources':searchable, 'verdict':'rag-scope-pending', 'mode':'sources-only',
                    'elapsed_s':round(time.time()-t0,3)}
        eligible = self.source_verifier.eligible_sources(q, retrieved)
        if not eligible:
            return {"answer": evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else 'אין במקורות שנמצאו ראיה מספקת למקרה שנשאל. נדרשים מקור מתאים ובדיקת ההקשר.', "sources": retrieved,
                    "verdict": "insufficient_context", "mode": "sources-only",
                    "human_review": "required", "halachic_verified": False,
                    "elapsed_s": round(time.time() - t0, 3)}
        retrieved = eligible
        # one LLM call
        try:
            generator=answer_model if answer_model is not None else self.answer_model
            if not hasattr(generator,'sent_sources'):
                from .request_budget import revalidate_sources
                retrieved=revalidate_sources(retrieved,self.knowledge.source_by_id)
            lr = generator.generate(q, retrieved, timeout=timeout)
            if hasattr(generator,'sent_sources'):
                retrieved=generator.sent_sources
            answer = lr["answer"]
            mode = "llm"
        except llm_client.LLMUnavailable as exc:
            from .request_budget import SourceChanged
            if isinstance(exc,SourceChanged):
                return {'answer':'המקור או ההרשאה השתנו; נדרשים אחזור ואימות מחדש.',
                        'sources':[],'verdict':'invalid_citation','mode':'llm-guarded',
                        'verification':{'verdict':'invalid_citation','support':'source changed before generation'},
                        'human_review':'required','halachic_verified':False}
            # Mac offline: sources only, clearly labeled
            stopped=getattr(getattr(generator,'budget',None),'reason',None)
            res = {"answer": evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else "מצב חיפוש (המודל אינו זמין): אלו המקורות הקרובים ביותר.",
                   "sources": retrieved, "verdict": "sources-only",
                   "mode": "sources-only", "elapsed_s": round(time.time() - t0, 3)}
            if stopped:
                res.update(answer='מצב חיפוש: הבקשה הגיעה למגבלת הזמן, הקריאות או ההקשר; אין תשובה מאומתת.',
                           verdict='budget_exhausted')
            if cacheable:self._cache[q] = (now, res)
            return dict(res)
        # safety verification
        # Rehydrate after generation: a provider call can outlive a grant or
        # source update. Never verify a stale prompt snapshot as current proof.
        from .request_budget import BudgetExceeded
        budget=getattr(generator,'budget',None)
        current=[]
        try:
            for source in retrieved:
                if budget:budget.check('post-generation source lookup')
                current.append(self.knowledge.source_by_id(source['source_id'],request_budget=budget))
                if budget:budget.check('post-generation source lookup return')
        except BudgetExceeded:
            return {'answer':'הבקשה הגיעה למגבלת הזמן; אין תשובה מאומתת.',
                    'sources':[],'verdict':'budget_exhausted','mode':'sources-only',
                    'human_review':'required','halachic_verified':False}
        stale=any(s is None or fingerprint(s)!=fingerprint(old) for s,old in zip(current,retrieved))
        v = ({'verdict':'invalid_citation','support':'source changed or unavailable after generation'} if stale else
             self.source_verifier.verify(q, answer, current))
        if stale:
            retrieved=[s for s in current if s is not None and rag_eligible(s)]
        if v['verdict'] in ('ok', 'no_source'):
            answer = v.get('rendered_answer', answer)
        if v['verdict'] == 'no_source' and evidence.shared_oil_waiting(q):
            answer = evidence.INSUFFICIENT
        verdict = v["verdict"]
        if verdict not in ("ok", "no_source"):
            # do not present as certain ruling
            answer = evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else "אין לי מקור לכך. " + " ".join(
                f"[{s.get('reference','')}]" for s in retrieved[:3])
            mode = "llm-guarded"
        supported = {e['source_id'] for e in v.get('evidence',[])}
        for source in retrieved:
            if source['source_id'] in supported:
                source['evidence_support']=v.get('support','exact-extract-only')
        res = {"answer": answer, "sources": retrieved, "verdict": verdict,
               "verification": v, "mode": mode,
               "human_review": "required", "halachic_verified": False,
               "elapsed_s": round(time.time() - t0, 3)}
        if cacheable:self._cache[q] = (now, res)
        return dict(res)

    def search_only(self, query, top_k=5, request_budget=None):
        if top_k<1:return []
        from .retrieval_budget import search_backend
        results=search_backend(self.search,retrieval_query(query),max(top_k*10,50),request_budget)
        ordered=order_sources(results,query)
        # Pending locators must not be promoted by diversity over usable passages.
        usable=[s for s in ordered if rag_eligible(s)]
        pending=[s for s in ordered if not rag_eligible(s)]
        selected=diverse_sources(usable,top_k)
        selected=selected+diverse_sources(pending,top_k-len(selected)) if len(selected)<top_k else selected
        return SearchResults(selected,getattr(results,'errors',[]))

    def converse(self, question, circumstances=None, research=False, **kwargs):
        from .orchestration import HalachicOrchestrator
        return HalachicOrchestrator(self).answer(question,circumstances,research,**kwargs)

    def conversation_turn(self, store, owner, conversation_id, question, circumstances=None, **kwargs):
        """Trusted local service caller only; memory never replaces retrieval."""
        return store.turn(self,owner,conversation_id,question,circumstances,**kwargs)

    def research(self, question, top_k=5, answer_model=None, local_sources=None, request_budget=None):
        from .web_research import WebResearchEngine
        if fastpath.is_out_of_scope(question):
            return self.ask(question)
        if self.research_engine is None:
            import os, json
            from pathlib import Path
            grants_path = os.environ.get('WEB_PERMISSIONS_PATH')
            grants = json.loads(Path(grants_path).read_text(encoding='utf-8')) if grants_path else {}
            self.research_engine = WebResearchEngine(grants=grants,
                store_path=os.environ.get('WEB_STORE_PATH','data/store/web/sources.jsonl'))
        engine = self.research_engine
        result = engine.answer(question, self.base_url, self.model, limit=top_k,
                             local_sources=[s for s in (self.search_only(question,top_k=top_k) if local_sources is None else local_sources) if rag_eligible(s)],
                             answer_model=answer_model if answer_model is not None else self.answer_model,
                             source_verifier=self.source_verifier,request_budget=request_budget,
                             source_resolver=self.knowledge.source_by_id)
        approved = [s for s in result.get('sources',[]) if s.get('source_project')=='verified-web'
                    and s.get('metadata',{}).get('persistence_allowed')]
        if approved and engine.store_path and (request_budget is None or request_budget.remaining()>0):
            self.knowledge.upsert_verified(approved)
            self._cache.clear()
        return result
