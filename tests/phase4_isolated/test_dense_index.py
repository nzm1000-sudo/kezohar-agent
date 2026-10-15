import json
import sqlite3
import pytest
from kezohar.embeddings import VectorIndexSpec, VectorIndexMismatch
from kezohar.library_search import SQLiteLibrarySearch
from kezohar.local_embeddings import EmbeddingUnavailable
from kezohar.vector_index import build, DenseIndex, DenseLibrarySearch

TOPICS = ['תפילין', 'ברכה', 'שבת', 'חנוכה']


class FakeModel:
    """Topic one-hot embeddings: a query matches texts sharing its topic word."""
    spec = VectorIndexSpec('fake', 'fake-model', 4, '1', 'raw-text-v1')
    down = False

    def _vec(self, text):
        v = [1.0 if t in text else 0.0 for t in TOPICS]
        return v if any(v) else [0.5] * 4

    def embed_many(self, texts, task='document', timeout=30):
        if self.down: raise EmbeddingUnavailable('down')
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self.embed_many([text], task='query')[0]


def library(tmp_path, n=10):
    path = tmp_path / 'lib' / 'library.sqlite3'
    path.parent.mkdir()
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE records (id TEXT PRIMARY KEY, file TEXT, payload TEXT)')
    for i in range(n):
        text = '' if i == 3 else f'הלכות {TOPICS[i % 4]} סעיף {i}'
        db.execute('INSERT INTO records VALUES (?,?,?)', (f's{i}', 'f', json.dumps({'source_id': f's{i}', 'text': text}, ensure_ascii=False)))
    db.commit()
    return path


def test_build_resumes_and_skips_empty(tmp_path):
    path, root = library(tmp_path), tmp_path / 'vectors'
    first = build(path, FakeModel(), root=root, batch=3, limit=4, log=None)
    assert first == {'count': 3, 'last_rowid': 4}  # row s3 has no text
    final = build(path, FakeModel(), root=root, batch=3, log=None)
    assert final == {'count': 9, 'last_rowid': 10}
    index = DenseIndex(path, FakeModel(), root=root)
    assert len(index) == 9 and 's3' not in index.ids
    assert len(set(index.ids)) == 9


def test_interrupted_tail_is_truncated(tmp_path):
    path, root = library(tmp_path), tmp_path / 'vectors'
    build(path, FakeModel(), root=root, batch=4, limit=4, log=None)
    out = next(root.glob('*/lib'))
    with open(out / 'vectors.f16', 'ab') as f: f.write(b'\0' * 8)  # torn write
    with open(out / 'ids.txt', 'a') as f: f.write('garbage\n')
    build(path, FakeModel(), root=root, batch=4, log=None)
    index = DenseIndex(path, FakeModel(), root=root)
    assert 'garbage' not in index.ids and len(index) == 9


def test_identity_change_requires_new_index(tmp_path):
    path, root = library(tmp_path), tmp_path / 'vectors'
    build(path, FakeModel(), root=root, log=None)
    other = FakeModel()
    other.spec = VectorIndexSpec('fake', 'fake-model', 4, '1', 'raw-text-v1')
    DenseIndex(path, other, root=root)  # same identity loads
    other_root = next(root.glob('*/lib')) / 'manifest.json'
    manifest = json.loads(other_root.read_text()); manifest['max_chars'] = 1
    other_root.write_text(json.dumps(manifest))
    with pytest.raises(VectorIndexMismatch):
        DenseIndex(path, FakeModel(), root=root)


def test_dense_backend_serves_library_payloads_and_degrades(tmp_path):
    path, root = library(tmp_path), tmp_path / 'vectors'
    model = FakeModel()
    build(path, model, root=root, log=None)
    backend = DenseLibrarySearch(SQLiteLibrarySearch(path), DenseIndex(path, model, root=root))
    hits = backend.search('מה הדין בתפילין', top_k=2)
    assert [h['source_id'] for h in hits] and all('תפילין' in h['text'] for h in hits)
    assert hits[0]['backend'] == 'dense-fake-model'
    model.down = True
    failed = backend.search('תפילין')
    assert list(failed) == [] and failed.errors[0]['error'] == 'embeddings-unavailable'


def test_dense_embeds_original_question_not_expanded_route(tmp_path):
    from kezohar.retrieval_plan import plan
    routes = plan('האם אפשר לשוחח באמצע הנחת תפילין?')['routes']
    assert all(r['query'].semantic_text == 'האם אפשר לשוחח באמצע הנחת תפילין?' for r in routes)
    path, root = library(tmp_path), tmp_path / 'vectors'
    model = FakeModel()
    build(path, model, root=root, log=None)
    seen = []
    model.embed_query = lambda text: seen.append(text) or model._vec(text)
    backend = DenseLibrarySearch(SQLiteLibrarySearch(path), DenseIndex(path, model, root=root))
    for r in routes: backend.search(r['query'], top_k=3)
    assert seen == ['האם אפשר לשוחח באמצע הנחת תפילין?']  # embedded once, cached across routes


def test_semantic_rerank_promotes_meaning_over_word_overlap():
    from types import SimpleNamespace
    from kezohar.agent import semantic_rerank
    model = FakeModel()
    search = SimpleNamespace(backends=[SimpleNamespace(index=SimpleNamespace(model=model))])
    eligible = {'rag_answers_allowed': True}
    lexical_first = {'source_id': 'a', 'text': 'הפסק בברכה בשבת', 'metadata': eligible}
    on_topic = {'source_id': 'b', 'text': 'דיבור בין תפילין', 'metadata': eligible}
    import kezohar.agent as agent_module
    original = agent_module.rag_eligible
    agent_module.rag_eligible = lambda s: True
    try:
        out = semantic_rerank([lexical_first, on_topic], 'מה הדין בתפילין', search)
        assert [s['source_id'] for s in out] == ['b', 'a']
        assert out[0]['semantic_similarity'] > out[1]['semantic_similarity']
        model.down = True  # embeddings unavailable: lexical order is kept untouched
        assert [s['source_id'] for s in semantic_rerank([lexical_first, on_topic], 'תפילין', search)] == ['a', 'b']
        assert semantic_rerank([lexical_first, on_topic], 'תפילין', SimpleNamespace(backends=[])) == [lexical_first, on_topic]
    finally:
        agent_module.rag_eligible = original


def test_priority_pass_then_full_pass_never_duplicates(tmp_path):
    path, root = library(tmp_path), tmp_path / 'vectors'
    db = sqlite3.connect(path)
    db.execute("UPDATE records SET payload=json_set(payload,'$.work_title','שופטים') WHERE id IN ('s7','s9')")
    db.commit()
    first = build(path, FakeModel(), root=root, batch=4, works=['שופטים'], log=None)
    assert first['count'] == 2
    final = build(path, FakeModel(), root=root, batch=4, log=None)
    index = DenseIndex(path, FakeModel(), root=root)
    assert final['count'] == 9 and len(set(index.ids)) == 9 and index.ids[:2] == ['s7', 's9']


def test_embed_text_strips_niqqud_and_cantillation_and_stale_index_is_ignored(tmp_path, monkeypatch):
    from kezohar.vector_index import embed_text, configured_index, index_dir
    assert embed_text('וַיְהִ֗י אַחֲרֵי־מ֣וֹת') == 'ויהי אחרי מות'
    path, root = library(tmp_path), tmp_path / 'vectors'
    model = FakeModel()
    build(path, model, root=root, log=None)
    manifest = index_dir(root, model.spec, path) / 'manifest.json'
    data = json.loads(manifest.read_text()); data['text_form'] = 'old'; manifest.write_text(json.dumps(data))
    import kezohar.embeddings as emb
    monkeypatch.setattr(emb, 'create_embedding_model', lambda settings=None: model)
    monkeypatch.setenv('EMBEDDINGS_PROVIDER', 'openai-compatible-local')
    assert configured_index(path, root=root) is None
