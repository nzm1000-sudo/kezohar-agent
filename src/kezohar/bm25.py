"""Local Hebrew BM25 search (stdlib only)."""
import math
from collections import Counter, defaultdict
from . import hebrew

class BM25Index:
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.docs = []  # list of Source
        self.doc_len = []
        self.avgdl = 0.0
        self.df = Counter()
        self.tf = []  # list of Counter
        self.N = 0
        self.postings = defaultdict(set)

    def add(self, sources):
        for s in sources:
            toks = hebrew.tokens(s.normalized_text or s.text)
            tf = Counter(toks)
            self.docs.append(s)
            self.tf.append(tf)
            self.doc_len.append(len(toks))
            for t in tf:
                self.df[t] += 1
                self.postings[t].add(len(self.docs)-1)
        self.N = len(self.docs)
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0

    def build(self, sources):
        self.__init__(k1=self.k1, b=self.b)
        self.add(sources)
        return self

    def _score_one(self, query_toks, idx):
        score = 0.0
        dl = self.doc_len[idx] or 1
        tf = self.tf[idx]
        for t in query_toks:
            f = tf.get(t, 0)
            if not f:
                continue
            df = self.df.get(t, 0)
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            score += idf * f * (self.k1 + 1) / denom
        # phrase bonus: exact normalized query substring
        return score

    def search(self, query, top_k=5):
        qtoks = hebrew.tokens(query)
        if not qtoks or not self.docs:
            return []
        qnorm = hebrew.normalize(query)
        scored = []
        candidates = set()
        for token in qtoks:
            candidates.update(self.postings.get(token, ()))
        for i in sorted(candidates):
            s = self.docs[i]
            sc = self._score_one(qtoks, i)
            if sc <= 0:
                continue
            # phrase bonus
            if qnorm and qnorm in (s.normalized_text or ""):
                sc *= 1.5
            scored.append({"source": s, "score": round(sc, 4)})
        # dedup by source_id keep max
        best = {}
        for r in scored:
            sid = r["source"].source_id
            if sid not in best or r["score"] > best[sid]["score"]:
                best[sid] = r
        ranked = sorted(best.values(), key=lambda r: -r["score"])[:top_k]
        out = []
        for r in ranked:
            s = r["source"]
            payload = s.to_dict()
            payload.update(score=r["score"], backend="bm25")
            out.append(payload)
        return out
