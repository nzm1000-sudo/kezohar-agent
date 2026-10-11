"""Hybrid search: BM25 + Vector with RRF fusion (k=60)."""
from .bm25 import BM25Index
from .vector import MockVectorStore

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
        self.vector = vector_store or MockVectorStore()
        if sources:
            self.bm25.build(sources)
            self.vector.add(sources)

    def search(self, query, top_k=5):
        b = self.bm25.search(query, top_k=top_k*2)
        v = self.vector.search(query, top_k=top_k*2)
        if not b and not v:
            return []
        if not b:
            return v[:top_k]
        if not v:
            return b[:top_k]
        return rrf_fuse([b, v], top_k=top_k)
