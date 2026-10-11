"""Vector store interface. Real Qdrant/BGE-M3 plugs in on NAS; Mock for local dev/test."""
import math
from . import config
from .embeddings import _embed_heuristic, create_embedding_model, VectorIndexSpec, VectorIndexMismatch

def cosine(a, b):
    return sum(x*y for x, y in zip(a, b))

class VectorStore:
    def add(self, sources): raise NotImplementedError
    def search(self, query, top_k=5): raise NotImplementedError
    def empty_copy(self): raise NotImplementedError

class MockVectorStore(VectorStore):
    """In-memory mock vector store for local dev. Marks backend='vector-mock'."""
    def __init__(self, dim=None, embedding_model=None):
        self._configured = embedding_model is None and dim is None
        if embedding_model is None:
            settings = config.embedding_settings()
            if dim is not None:
                from dataclasses import replace
                settings = replace(settings, dimensions=dim)
            embedding_model = create_embedding_model(settings)
        self.embedding_model = embedding_model
        self.index_spec = embedding_model.spec
        self.dim = self.index_spec.dimensions
        self.docs = []
        self.vecs = []

    @property
    def revision(self):
        current = VectorIndexSpec.from_settings(config.embedding_settings()) if self._configured else self.embedding_model.spec
        return (self.index_spec.namespace, current.namespace)

    def empty_copy(self):
        return MockVectorStore() if self._configured else MockVectorStore(embedding_model=self.embedding_model)

    def _embed(self, text):
        current = VectorIndexSpec.from_settings(config.embedding_settings()) if self._configured else self.embedding_model.spec
        self.index_spec.check_manifest(current.manifest())
        vector = self.embedding_model.embed(text)
        if len(vector) != self.dim or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
            raise VectorIndexMismatch('embedding output dimension or values do not match index')
        return vector

    def add(self, sources):
        for s in sources:
            vector = self._embed(s.normalized_text or s.text)
            self.docs.append(s)
            self.vecs.append(vector)

    def search(self, query, top_k=5):
        if not self.docs:
            return []
        qv = self._embed(query)
        scored = []
        for s, v in zip(self.docs, self.vecs):
            scored.append({"source": s, "score": cosine(qv, v)})
        scored.sort(key=lambda r: -r["score"])
        out = []
        for r in scored[:top_k]:
            s = r["source"]
            if r["score"] <= 0:
                continue
            payload = s.to_dict()
            payload.update(score=round(r["score"], 4), backend="vector-mock")
            out.append(payload)
        return out
