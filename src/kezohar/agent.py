"""Agent orchestration: fastpath -> retrieval (code) -> one LLM call -> safety check."""
import time
from . import fastpath, citations, llm as llm_client, config
from .hybrid import HybridSearch
from .ingest import load_store

TRADITION_ORDER = {"sephardi": 0, "": 1, "ashkenazi": 2}

def order_sources(sources):
    """Maran/Sephardi first, then others — stable within groups."""
    return sorted(sources, key=lambda s: (TRADITION_ORDER.get(s.get("tradition", ""), 1), -s.get("score", 0)))

class Agent:
    def __init__(self, sources=None, store_path=None, base_url=None, model=None):
        if sources is None:
            sources = load_store(store_path) if store_path else []
        self.search = HybridSearch(sources)
        self.base_url = base_url if base_url is not None else config.llm_base_url()
        self.model = model or config.llm_model()
        self._cache = {}  # q -> (ts, result)

    def ask(self, question, top_k=5, lat=None, lon=None, location=None, timeout=60, cache_ttl=300):
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
        retrieved = order_sources(self.search.search(q, top_k=top_k))
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
        v = citations.verify_answer(q, answer, retrieved)
        verdict = v["verdict"]
        if verdict not in ("ok", "no_source"):
            # do not present as certain ruling
            answer = "אין לי מקור לכך. " + " ".join(
                f"[{s.get('reference','')}]" for s in retrieved[:3])
            mode = "llm-guarded"
        res = {"answer": answer, "sources": retrieved, "verdict": verdict,
               "verification": v, "mode": mode,
               "elapsed_s": round(time.time() - t0, 3)}
        self._cache[q] = (now, res)
        return dict(res)

    def search_only(self, query, top_k=5):
        return order_sources(self.search.search(query, top_k=top_k))
