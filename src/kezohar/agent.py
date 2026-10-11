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

TRADITION_ORDER = {"sephardi": 0, "": 1, "ashkenazi": 2}

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
    return sorted(sources, key=lambda s: (
        s.get('domain') != 'halacha',
        TRADITION_ORDER.get(s.get('tradition',''),1),
        s.get('halachic_authority')!='maran',
        s.get('source_type')!='psak-code',
        -s.get('topical_overlap',0),
        s.get('category') not in ('halacha','responsa'),
        -s.get('score',0)))


class Agent:
    def __init__(self, sources=None, store_path=None, base_url=None, model=None, research_engine=None,
                 knowledge=None, search_engine=None, answer_model=None, source_verifier=None):
        self.knowledge = knowledge if knowledge is not None else KnowledgeBase(sources, store_path, search_engine)
        self.answer_model = answer_model if answer_model is not None else ConfiguredAnswerModel(base_url, model)
        self.source_verifier = source_verifier if source_verifier is not None else ExtractiveSourceVerifier()
        self.research_engine = research_engine
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

    def ask(self, question, top_k=5, lat=None, lon=None, location=None, timeout=4.5, cache_ttl=300, retrieved_sources=None):
        t0 = time.time()
        q = (question or "").strip()
        if not q:
            return {"answer": "נא לשאול שאלה.", "sources": [], "verdict": "empty",
                    "mode": "refuse", "elapsed_s": 0.0}
        # Permission/index changes invalidate answers derived from older records.
        revision = (getattr(self.search,"revision",None), self.answer_model.identity)
        if revision != self._cache_revision:
            self._cache.clear()
            self._cache_revision = revision
        # cache
        now = time.time()
        if q in self._cache:
            ts, res = self._cache[q]
            if now - ts < cache_ttl:
                r = dict(res)
                r["cached"] = True
                return r
        # out of scope -> polite refusal (no retrieval needed, but include empty sources)
        if fastpath.is_out_of_scope(q):
            res = {"answer": "מצטער, אני עונה רק על הלכה, מנהגים, ברכות, זמנים, תפילות, צומות, שבת, חגים ולוח השנה העברי.",
                   "sources": [], "verdict": "out_of_scope", "mode": "refuse",
                   "elapsed_s": round(time.time() - t0, 3)}
            self._cache[q] = (now, res)
            return dict(res)
        # fast path (zmanim/calendar) — no LLM
        fp = fastpath.handle(q, lat=lat or fastpath.DEFAULT_LAT, lon=lon or fastpath.DEFAULT_LON,
                             location=location or fastpath.DEFAULT_LOCATION)
        if fp is not None:
            res = {"answer": fp["answer"], "sources": [], "verdict": fp["kind"],
                   "mode": "fast", "details": fp, "elapsed_s": round(time.time() - t0, 3)}
            self._cache[q] = (now, res)
            return dict(res)
        # retrieval first (in code)
        retrieved = retrieved_sources if retrieved_sources is not None else self.search_only(q,top_k=top_k)
        if not retrieved:
            res = {"answer": evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else "אין לי מקור לכך.", "sources": [],
                   "verdict": "no_source", "mode": "sources-only",
                   "elapsed_s": round(time.time() - t0, 3)}
            self._cache[q] = (now, res)
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
            lr = self.answer_model.generate(q, retrieved, timeout=timeout)
            answer = lr["answer"]
            mode = "llm"
        except llm_client.LLMUnavailable:
            # Mac offline: sources only, clearly labeled
            res = {"answer": evidence.INSUFFICIENT if evidence.shared_oil_waiting(q) else "מצב חיפוש (המודל אינו זמין): אלו המקורות הקרובים ביותר.",
                   "sources": retrieved, "verdict": "sources-only",
                   "mode": "sources-only", "elapsed_s": round(time.time() - t0, 3)}
            self._cache[q] = (now, res)
            return dict(res)
        # safety verification
        v = self.source_verifier.verify(q, answer, retrieved)
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
        self._cache[q] = (now, res)
        return dict(res)

    def search_only(self, query, top_k=5):
        return order_sources(self.search.search(retrieval_query(query), top_k=max(top_k*10,50)),query)[:top_k]

    def research(self, question, top_k=5):
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
                             local_sources=[s for s in self.search_only(question,top_k=top_k) if rag_eligible(s)],
                             answer_model=self.answer_model, source_verifier=self.source_verifier)
        approved = [s for s in result.get('sources',[]) if s.get('source_project')=='verified-web'
                    and s.get('metadata',{}).get('persistence_allowed')]
        if approved and engine.store_path:
            self.knowledge.upsert_verified(approved)
            self._cache.clear()
        return result
