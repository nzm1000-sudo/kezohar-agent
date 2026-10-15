"""Persistent dense index over an existing SQLite library (no copy of texts).

Layout per (embedding namespace, library): manifest.json, ids.txt, vectors.f16
(float16, L2-normalized rows) and progress.json. Appends are resumable; on
restart files are truncated to the last committed count. Payloads are always
read back from the library itself, so permissions/locators stay authoritative.
"""
import json
import os
import sqlite3
from pathlib import Path
from . import config
from .embeddings import VectorIndexSpec, VectorIndexMismatch

MAX_CHARS = 2000  # ponytail: head of each unit only; split long units if recall suffers


def index_dir(root, spec, library_path):
    return Path(root) / spec.namespace / Path(library_path).resolve().parent.name


def _manifest(spec, library_path):
    return {**spec.manifest(), 'library': str(Path(library_path).resolve()), 'max_chars': MAX_CHARS}


def _write_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def build(library_path, model, root='data/store/vectors', batch=16, limit=None, log=print):
    """Embed library records in rowid order, resuming after the last commit."""
    import numpy as np
    out = index_dir(root, model.spec, library_path)
    out.mkdir(parents=True, exist_ok=True)
    if hasattr(model, 'slot_path'):
        model.slot_path = out / 'build.lock'  # separate from the answer slot
    manifest = _manifest(model.spec, library_path)
    mpath = out / 'manifest.json'
    if mpath.exists() and json.loads(mpath.read_text()) != manifest:
        raise VectorIndexMismatch('existing index has another identity; use a new directory')
    _write_json(mpath, manifest)
    ppath = out / 'progress.json'
    progress = json.loads(ppath.read_text()) if ppath.exists() else {'count': 0, 'last_rowid': 0}
    dim = model.spec.dimensions
    ids_path, vec_path = out / 'ids.txt', out / 'vectors.f16'
    # Drop any uncommitted tail left by an interrupted batch.
    with open(vec_path, 'ab') as f: f.truncate(progress['count'] * dim * 2)
    ids = ids_path.read_text().splitlines()[:progress['count']] if ids_path.exists() else []
    ids_path.write_text(''.join(i + '\n' for i in ids))
    db = sqlite3.connect(Path(library_path).resolve().as_uri() + '?mode=ro', uri=True)
    done = 0
    while limit is None or done < limit:
        n = batch if limit is None else min(batch, limit - done)
        rows = db.execute("SELECT rowid,id,json_extract(payload,'$.text') FROM records WHERE rowid>? ORDER BY rowid LIMIT ?",
                          (progress['last_rowid'], n)).fetchall()
        if not rows:
            break
        keep = [(sid, text.strip()[:MAX_CHARS]) for _, sid, text in rows if isinstance(text, str) and text.strip()]
        if keep:
            vectors = np.asarray(model.embed_many([t for _, t in keep], timeout=120), dtype=np.float16)
            with open(vec_path, 'ab') as f: f.write(vectors.tobytes())
            with open(ids_path, 'a') as f: f.write(''.join(sid + '\n' for sid, _ in keep))
        progress = {'count': progress['count'] + len(keep), 'last_rowid': rows[-1][0]}
        _write_json(ppath, progress)
        done += len(rows)
        if log and progress['count'] % 1600 < len(keep):
            log(json.dumps(progress))
    return progress


class DenseIndex:
    def __init__(self, library_path, model, root='data/store/vectors'):
        import numpy as np
        self.model, self.spec = model, model.spec
        out = index_dir(root, model.spec, library_path)
        if json.loads((out / 'manifest.json').read_text()) != _manifest(model.spec, library_path):
            raise VectorIndexMismatch('dense index identity does not match configured embeddings')
        count = json.loads((out / 'progress.json').read_text())['count']
        self.ids = (out / 'ids.txt').read_text().splitlines()[:count]
        self.matrix = np.fromfile(out / 'vectors.f16', dtype=np.float16, count=count * self.spec.dimensions
                                  ).reshape(count, self.spec.dimensions)

    def __len__(self):
        return len(self.ids)

    def search(self, query, top_k=10):
        import numpy as np
        if not self.ids:
            return []
        q = np.asarray(self.model.embed_query(str(query)), dtype=np.float16)
        scores = self.matrix @ q
        k = min(top_k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        return [(self.ids[i], float(scores[i])) for i in top[np.argsort(-scores[top])]]


class DenseLibrarySearch:
    """Federated backend: semantic neighbours, payloads read from the library."""
    def __init__(self, library, index):
        self.library, self.index = library, index
        self._cache = {}  # several routes of one request share the same question

    def _hits(self, text, top_k):
        key = (text, top_k)
        if key not in self._cache:
            if len(self._cache) > 64: self._cache.clear()
            self._cache[key] = self.index.search(text, top_k=top_k)
        return self._cache[key]

    @property
    def revision(self):
        return ('dense', self.index.spec.namespace, len(self.index), self.library.revision)

    def search(self, query, top_k=5, request_budget=None):
        from .local_embeddings import EmbeddingUnavailable
        from .hybrid import SearchResults
        if request_budget: request_budget.check('dense retrieval')
        try:
            hits = self._hits(getattr(query, 'semantic_text', None) or str(query), top_k)
        except EmbeddingUnavailable:
            return SearchResults([], [{'backend': 'dense', 'error': 'embeddings-unavailable'}])
        out = []
        for sid, score in hits:
            source = self.library.source_by_id(sid, request_budget=request_budget)
            if source is not None:  # removed or revoked rows are never served from vectors
                source.update(score=round(score, 4), semantic_similarity=round(score, 4), backend='dense-' + self.index.spec.model)
                out.append(source)
        return SearchResults(out)


def configured_index(library_path, root=None):
    """Return a DenseIndex when real local embeddings are configured and built."""
    settings = config.embedding_settings()
    if settings.provider != 'openai-compatible-local':
        return None
    from .embeddings import create_embedding_model
    root = root or config.get('VECTOR_INDEX_DIR', 'data/store/vectors')
    model = create_embedding_model(settings)
    if not (index_dir(root, model.spec, library_path) / 'progress.json').exists():
        return None
    return DenseIndex(library_path, model, root)
