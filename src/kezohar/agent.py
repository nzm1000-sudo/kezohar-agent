"""Agent orchestration: fastpath -> retrieval (code) -> one LLM call -> safety check."""
import time
from . import fastpath, citations, llm as llm_client, config
from .hybrid import HybridSearch
from .ingest import load_store
from .ranking import topic_tokens, retrieval_query, topic_overlap

TRADITION_ORDER = {"sephardi": 0, "": 1, "ashkenazi": 2}

def order_sources(sources, question=""):
    """Maran/Sephardi first, then others — stable within groups."""
    if question:
        terms = topic_tokens(question)
        if terms:
            sources = [s for s in sources if topic_overlap(s.get('text',''),question)>0]
    for source in sources:
        source['topical_overlap'] = topic_overlap(source.get('text',''),question) if question else 0
        source.setdefault('search_relevance', source.get('score',0))
        source.setdefault('source_reliability', source.get('metadata',{}).get('source_reliability','import-provenance-only'))
        source.setdefault('halachic_authority', source.get('authority_level','') or ('maran' if source.get('work_title','').startswith('שולחן ערוך') or source.get('book_id')=='Beit_Yosef' else 'unclassified'))
        source.setdefault('evidence_support', 'not-claim-verified')
    return sorted(sources, key=lambda s: (
        -s.get('topical_overlap',0),
        TRADITION_ORDER.get(s.get('tradition',''),1),
        s.get('halachic_authority')!='maran',
        s.get('category') not in ('halacha','responsa'),
        -s.get('score',0)))


class Agent:
    def __init__(self, sources=None, store_path=None, base_url=None, model=None, research_engine=None):
        if sources is None:
            sources = []
            if store_path:
                paths = store_path if isinstance(store_path, (list, tuple)) else [store_path]
                unique = {}
                for path in paths:
                    for source in load_store(path):
                        unique[source.source_id] = source
                sources = list(unique.values())
        self.search = HybridSearch(sources)
        self.base_url = base_url if base_url is not None else config.llm_base_url()
        self.model = model or config.llm_model()
        self.research_engine = research_engine
        self._cache = {}  # q -> (ts, result)

    def ask(self, question, top_k=5, lat=None, lon=None, location=None, timeout=4.5, cache_ttl=300, retrieved_sources=None):
        t0 = time.time()
        q = (question or "").strip()
        if not q:
            return {"answer": "נא לשאול שאלה.", "sources": [], "verdict": "empty",
                    "mode": "refuse", "elapsed_s": 0.0}
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
            res = {"answer": "אין לי מקור לכך.", "sources": [],
                   "verdict": "no_source", "mode": "sources-only",
                   "elapsed_s": round(time.time() - t0, 3)}
            self._cache[q] = (now, res)
            return dict(res)
        # one LLM call
        try:
            lr = llm_client.ask(q, retrieved, self.base_url, self.model, timeout=timeout)
            answer = lr["answer"]
            mode = "llm"
        except llm_client.LLMUnavailable:
            # Mac offline: sources only, clearly labeled
            res = {"answer": "מצב חיפוש (המודל אינו זמין): אלו המקורות הקרובים ביותר.",
                   "sources": retrieved, "verdict": "sources-only",
                   "mode": "sources-only", "elapsed_s": round(time.time() - t0, 3)}
            self._cache[q] = (now, res)
            return dict(res)
        # safety verification
        v = citations.verify_extractive_answer(answer, retrieved)
        if 'אין לי מקור' in answer and answer.strip().rstrip('.')=='אין לי מקור לכך':
            v = {'verdict':'no_source', 'support':'no claim'}
        elif v['verdict']=='ok' and not any(citations.check_relevance(s['text'],q)[0] for s in retrieved):
            v = {'verdict':'irrelevant', 'support':'quotation unrelated to question'}
        verdict = v["verdict"]
        if verdict not in ("ok", "no_source"):
            # do not present as certain ruling
            answer = "אין לי מקור לכך. " + " ".join(
                f"[{s.get('reference','')}]" for s in retrieved[:3])
            mode = "llm-guarded"
        supported = {e['source_id'] for e in v.get('evidence',[])}
        for source in retrieved:
            if source['source_id'] in supported:
                source['evidence_support']='exact-extract-only'
        res = {"answer": answer, "sources": retrieved, "verdict": verdict,
               "verification": v, "mode": mode,
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
                             local_sources=self.search_only(question,top_k=top_k))
        approved = [s for s in result.get('sources',[]) if s.get('source_project')=='verified-web'
                    and s.get('metadata',{}).get('persistence_allowed')]
        if approved and engine.store_path:
            from .models import Source
            primary = getattr(self.search,'primary',self.search)
            merged = {s.source_id:s for s in primary.bm25.docs}
            merged.update({s['source_id']:Source.from_dict(s) for s in approved})
            updated = HybridSearch(list(merged.values()))
            if hasattr(self.search,'primary'):
                self.search.primary = updated
                self.search.bm25, self.search.vector = updated.bm25, updated.vector
            else:
                self.search = updated
            self._cache.clear()
        return result
