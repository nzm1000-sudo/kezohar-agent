"""Hybrid search: BM25 + Vector with RRF fusion (k=60)."""
from .bm25 import BM25Index
from . import config
from .vector import MockVectorStore
from .embeddings import VectorIndexMismatch
from .source_snapshot import fingerprint


class SearchResults(list):
    """List-compatible, request-local status; no shared mutable last_error."""
    def __init__(self, sources=(), errors=()):
        super().__init__(sources)
        self.errors=list(errors)
    @property
    def status(self):
        return {'partial':bool(self.errors),'errors':self.errors}

RRF_K = 60

def rrf_fuse(rank_lists, k=RRF_K, top_k=5):
    """rank_lists: list of ranked lists (each item has source_id). Returns fused ordering."""
    scores = {}
    payload = {}
    conflicts=set()
    for lst in rank_lists:
        for rank, item in enumerate(lst, start=1):
            sid = item["source_id"]
            if sid in conflicts:continue
            if sid in payload and fingerprint(payload[sid])!=fingerprint(item):
                conflicts.add(sid);payload.pop(sid);scores.pop(sid,None)
                continue
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
    return SearchResults(sorted(payload.values(), key=lambda r: -r["score"])[:top_k],
                         [{'stage':'identity','source_id':sid,'error':'conflicting-source-snapshots'} for sid in sorted(conflicts)])

class HybridSearch:
    def __init__(self, sources=None, vector_store=None):
        self.bm25 = BM25Index()
        self.vector = None if vector_store is False else (vector_store if vector_store is not None else
            (MockVectorStore() if config.get('EMBEDDINGS_PROVIDER','mock')=='mock'
             and (not sources or len(sources) <= 10000) else None))
        self.vector_status = 'ready' if self.vector is not None else 'disabled'
        if sources:
            self.bm25.build(sources)
            if self.vector is not None:
                self.vector.add(sources)

    @property
    def revision(self):
        return (id(self.bm25),tuple(fingerprint(s.to_dict()) for s in self.bm25.docs),
                getattr(self.vector, 'revision', None))

    def search(self, query, top_k=5, request_budget=None):
        if request_budget:request_budget.check('hybrid retrieval')
        b = self.bm25.search(query, top_k=top_k*2)
        try:
            if request_budget:request_budget.check('vector retrieval')
            v = self.vector.search(query, top_k=top_k*2) if self.vector is not None else []
            self.vector_status = 'ready' if self.vector is not None else 'disabled'
        except VectorIndexMismatch:
            self.vector_status = 'reindex-required'
            v = []  # lexical search remains available; never mix embedding spaces.
        fused=rrf_fuse([b,v],top_k=top_k)
        errors=getattr(b,'errors',[])+getattr(v,'errors',[])+fused.errors
        blocked={e['source_id'] for e in errors if e.get('stage')=='identity'}
        return SearchResults([s for s in fused if s['source_id'] not in blocked],errors)


class FederatedSearch:
    """Fuse local, large app-library and verified research retrieval by rank."""
    def __init__(self, primary, backends):
        self.primary = primary
        self.backends = backends
        self.bm25 = primary.bm25
        self.vector = primary.vector
        import threading
        self._diagnostics=threading.local()

    @property
    def errors(self):
        return getattr(self._diagnostics,'errors',[])

    @property
    def revision(self):
        return (getattr(self.primary,"revision",None), tuple(getattr(backend,"revision",None) for backend in self.backends))

    @property
    def source_count(self):
        return len(self.bm25.docs)+sum(getattr(backend,'source_count',0) for backend in self.backends)

    def search(self, query, top_k=5, request_budget=None):
        # SQLite backends open a connection per search. Keep the primary index
        # in the calling thread; overlap independent disk lookups only.
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from .request_budget import BudgetExceeded
        from .retrieval_budget import search_backend
        if request_budget:request_budget.check('federated retrieval')
        ranked=[];errors=[];futures=[]
        pool=ThreadPoolExecutor(max_workers=min(3,max(1,len(self.backends))))
        try:
            for index,backend in enumerate(self.backends):
                if request_budget:request_budget.check('backend submission')
                futures.append((index,pool.submit(search_backend,backend,query,top_k*2,request_budget)))
            try:
                results=search_backend(self.primary,query,top_k*2,request_budget)
                ranked.append(results);errors.extend(getattr(results,'errors',[]))
            except BudgetExceeded:raise
            except Exception as exc:
                errors.append({'backend':'primary','error':type(exc).__name__})
            for index,future in futures:
                try:
                    if request_budget:request_budget.check('backend wait')
                    results=future.result(timeout=request_budget.remaining() if request_budget else None)
                    ranked.append(results)
                    errors.extend(getattr(results,'errors',[]))
                except (BudgetExceeded,TimeoutError):
                    if request_budget:request_budget.reason='retrieval exceeded request deadline'
                    errors.append({'backend':index,'error':'deadline-exhausted'})
                except Exception as exc:
                    errors.append({'backend':index,'error':type(exc).__name__})
        except BudgetExceeded:
            errors.append({'stage':'retrieval','error':'deadline-exhausted'})
        finally:
            for _,future in futures:future.cancel()
            # Running workers cannot be killed by Python; queued work is cancelled
            # and supported backends check the same deadline before further I/O.
            pool.shutdown(wait=request_budget is None,cancel_futures=True)
        merged=rrf_fuse(ranked,top_k=top_k)
        self._diagnostics.errors=errors+merged.errors
        blocked={e['source_id'] for e in self.errors if e.get('stage')=='identity'}
        return SearchResults([s for s in merged if s['source_id'] not in blocked],self.errors)
