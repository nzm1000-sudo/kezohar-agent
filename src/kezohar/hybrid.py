"""Hybrid search: BM25 + Vector with RRF fusion (k=60)."""
from .bm25 import BM25Index
from .vector import MockVectorStore
from .embeddings import VectorIndexMismatch

RRF_K = 60

def rrf_fuse(rank_lists, k=RRF_K, top_k=5):
    """rank_lists: list of ranked lists (each item has source_id). Returns fused ordering."""
    scores = {}
    payload = {}
    for lst in rank_lists:
        for rank, item in enumerate(lst, start=1):
            sid = item["source_id"]
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (k + rank)
            # keep best payload (prefer bm25 text, merge backends)
            if sid not in payload:
                payload[sid] = dict(item)
            else:
                prev = payload[sid]
                prev["backend"] = prev.get("backend", "") + "+" + item.get("backend", "")
                prev["score"] = round(scores[sid], 4)
    for sid, sc in scores.items():
        payload[sid]["score"] = round(sc, 4)
        payload[sid]["backend"] = "hybrid:" + payload[sid].get("backend", "")
    return sorted(payload.values(), key=lambda r: -r["score"])[:top_k]

class HybridSearch:
    def __init__(self, sources=None, vector_store=None):
        self.bm25 = BM25Index()
        self.vector = None if vector_store is False else (vector_store if vector_store is not None else
            (MockVectorStore() if not sources or len(sources) <= 10000 else None))
        self.vector_status = 'ready' if self.vector is not None else 'disabled'
        if sources:
            self.bm25.build(sources)
            if self.vector is not None:
                self.vector.add(sources)

    @property
    def revision(self):
        return (id(self.bm25), getattr(self.vector, 'revision', None))

    def search(self, query, top_k=5):
        b = self.bm25.search(query, top_k=top_k*2)
        try:
            v = self.vector.search(query, top_k=top_k*2) if self.vector is not None else []
            self.vector_status = 'ready' if self.vector is not None else 'disabled'
        except VectorIndexMismatch:
            self.vector_status = 'reindex-required'
            v = []  # lexical search remains available; never mix embedding spaces.
        if not b and not v:
            return []
        if not b:
            return v[:top_k]
        if not v:
            return b[:top_k]
        return rrf_fuse([b, v], top_k=top_k)


class FederatedSearch:
    """Fuse local, large app-library and verified research retrieval by rank."""
    def __init__(self, primary, backends):
        self.primary = primary
        self.backends = backends
        self.bm25 = primary.bm25
        self.vector = primary.vector

    @property
    def revision(self):
        return (getattr(self.primary,"revision",None), tuple(getattr(backend,"revision",None) for backend in self.backends))

    @property
    def source_count(self):
        return len(self.bm25.docs)+sum(getattr(backend,'source_count',0) for backend in self.backends)

    def search(self, query, top_k=5):
        # SQLite backends open a connection per search. Keep the primary index
        # in the calling thread; overlap independent disk lookups only.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(3,max(1,len(self.backends)))) as pool:
            futures=[pool.submit(backend.search,query,top_k=top_k*2) for backend in self.backends]
            ranked=[self.primary.search(query,top_k=top_k*2)]
            ranked.extend(future.result() for future in futures)
        return rrf_fuse(ranked, top_k=top_k)
