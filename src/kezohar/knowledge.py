"""Source corpus and its retrieval engines; no answer-model configuration here."""
from .ingest import load_store
from .hybrid import HybridSearch
from .models import Source
from .source_snapshot import fingerprint, unique_sources


class KnowledgeBase:
    def __init__(self, sources=None, store_path=None, search_engine=None):
        if search_engine is not None:
            self.search = search_engine
            return
        if sources is None:
            loaded = []
            paths = store_path if isinstance(store_path, (list, tuple)) else [store_path]
            for path in paths:
                if path:
                    for source in load_store(path):
                        if source.source_project=='verified-web':
                            # A disk record proves a past read, not current web
                            # content or permissions. Reuse URL metadata through
                            # live research; never revive a cached ruling here.
                            source.metadata=dict(source.metadata if isinstance(source.metadata,dict) else {},rag_answers_allowed=False,
                                web_cache_status='live-read-and-policy-revalidation-required')
                        loaded.append(source)
            sources = loaded  # retain conflicting IDs for fail-closed resolution
        self.search = HybridSearch(sources)

    def status(self):
        primary = getattr(self.search, 'primary', self.search)
        vector = getattr(primary, 'vector', None)
        count = getattr(self.search, 'source_count', None)
        if count is None:
            count = len(primary.bm25.docs) if hasattr(primary, 'bm25') else None
        state = getattr(primary, 'vector_status', 'external')
        revision = getattr(vector, 'revision', None)
        if isinstance(revision, tuple) and len(revision) == 2 and revision[0] != revision[1]:
            state = 'reindex-required'
        spec = getattr(vector, 'index_spec', None)
        return {'source_count': count, 'vector_status': state,
                'vector_kind':'disabled' if vector is None else 'heuristic-mock' if spec and spec.provider=='mock' else 'semantic-real' if spec and spec.provider=='openai-compatible-local' else 'external-unclassified',
                'vector_index': spec.manifest() if spec is not None else None}

    def source_by_id(self, source_id, request_budget=None):
        from .retrieval_budget import accepts_budget
        if request_budget:request_budget.check('source lookup')
        primary=getattr(self.search,'primary',self.search)
        matches=[]
        for source in getattr(getattr(primary,'bm25',None),'docs',[]):
            if source.source_id==source_id:matches.append(source.to_dict())
        for backend in getattr(self.search,'backends',[]):
            lookup=getattr(backend,'source_by_id',None)
            if lookup is not None:
                if request_budget:request_budget.check('source lookup backend')
                opts={'request_budget':request_budget} if request_budget and accepts_budget(lookup) else {}
                source=lookup(source_id,**opts)
                if request_budget:request_budget.check('source lookup backend return')
                if source is not None:matches.append(source)
        if not matches:return None
        # An ID collision must not silently serve a different text or locator.
        identities={fingerprint(s) for s in matches}
        return matches[0] if len(identities)==1 else None

    def upsert_verified(self, sources):
        """Update the small verified-source corpus, preserving app disk backends."""
        primary = getattr(self.search, 'primary', self.search)
        replacements=unique_sources(sources)
        merged=[s for s in primary.bm25.docs if s.source_id not in replacements]
        merged.extend(Source.from_dict(s) for s in replacements.values())
        # Preserve embedding provider/disablement; no dependency on answer settings.
        vector = primary.vector.empty_copy() if primary.vector is not None else False
        updated = HybridSearch(merged, vector_store=vector)
        if hasattr(self.search, 'primary'):
            self.search.primary = updated
            self.search.bm25, self.search.vector = updated.bm25, updated.vector
        else:
            self.search = updated
