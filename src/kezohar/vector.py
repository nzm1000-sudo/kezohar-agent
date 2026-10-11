"""Vector store interface. Real Qdrant/BGE-M3 plugs in on NAS; Mock for local dev/test."""
import hashlib
import math
from . import hebrew

def _embed_heuristic(text, dim=128):
    """Cheap deterministic char-trigram hash embedding (Mock only).
    NOT a real semantic model — used for interface/tests, never reported as perf."""
    toks = hebrew.tokens(text)
    vec = [0.0] * dim
    for t in toks:
        for i in range(len(t)):
            tri = t[max(0, i-1):i+2]
            h = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16) % dim
            vec[h] += 1.0
    n = math.sqrt(sum(v*v for v in vec)) or 1.0
    return [v/n for v in vec]

def cosine(a, b):
    return sum(x*y for x, y in zip(a, b))

class VectorStore:
    def add(self, sources): raise NotImplementedError
    def search(self, query, top_k=5): raise NotImplementedError

class MockVectorStore(VectorStore):
    """In-memory mock vector store for local dev. Marks backend='vector-mock'."""
    def __init__(self, dim=128):
        self.dim = dim
        self.docs = []
        self.vecs = []

    def add(self, sources):
        for s in sources:
            self.docs.append(s)
            self.vecs.append(_embed_heuristic(s.normalized_text or s.text, self.dim))

    def search(self, query, top_k=5):
        if not self.docs:
            return []
        qv = _embed_heuristic(query, self.dim)
        scored = []
        for s, v in zip(self.docs, self.vecs):
            scored.append({"source": s, "score": cosine(qv, v)})
        scored.sort(key=lambda r: -r["score"])
        out = []
        for r in scored[:top_k]:
            s = r["source"]
            if r["score"] <= 0:
                continue
            out.append({"source_id": s.source_id, "work_title": s.work_title,
                        "reference": s.reference, "text": s.text,
                        "license": s.license, "tradition": s.tradition,
                        "score": round(r["score"], 4), "backend": "vector-mock"})
        return out
