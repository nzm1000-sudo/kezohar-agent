"""The ready answer bank's vectors in Qdrant Cloud (owner, 2026-10-22: the search off the Mac). Same rows and vectors as
qa_bank.py (bge-m3 1024, the checked answers in their new wording), collection `rav_bari_bank`, cosine, int8 in memory.

Usage: qdrant_bank.py upload | compare | books
  books: the halachot of book-units.json (ילקוט יוסף, הכשרות למעשה, the Torat Emet books) in `rav_bari_books` — the
         sources found in the cloud too (owner, 2026-10-22). Embedded by the Mac's own bge-m3 (the same vectors).
         Resumable: points already there are skipped.
Reads QDRANT_URL and QDRANT_API_KEY from .env; the vectors from data/store/qa-bank/answers.vectors.json (no embedding).
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
ENV = {l.split('=', 1)[0]: l.split('=', 1)[1].strip() for l in (ROOT / '.env').read_text().splitlines() if '=' in l and not l.startswith('#')}
URL, KEY, NAME = ENV['QDRANT_URL'].rstrip('/'), ENV['QDRANT_API_KEY'], 'rav_bari_bank'


def call(method, path, body=None):
    req = urllib.request.Request(URL + path, json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={'api-key': KEY, 'Content-Type': 'application/json', 'User-Agent': 'kezohar-agent/1.0'})
    return json.load(urllib.request.urlopen(req, timeout=120))


class _NoEmbed:
    def embed_many(self, texts):
        raise RuntimeError(f'{len(texts)} bank questions have no cached vector — run the agent once first')


def bank():
    from kezohar.qa_bank import _load
    return _load(_NoEmbed())


def upload():
    rows, vectors = bank()
    try:
        call('DELETE', f'/collections/{NAME}')
    except Exception:
        pass
    call('PUT', f'/collections/{NAME}', {'vectors': {'size': 1024, 'distance': 'Cosine', 'on_disk': True},
                                          'quantization_config': {'scalar': {'type': 'int8', 'always_ram': True}}})
    for i in range(0, len(rows), 256):
        points = [{'id': i + j, 'vector': v, 'payload': {'q': r['q'], 'topic': r.get('topic', '')}}
                  for j, (r, v) in enumerate(zip(rows[i:i + 256], vectors[i:i + 256]))]
        call('PUT', f'/collections/{NAME}/points?wait=true', {'points': points})
        if i % 5120 == 0:
            print(f'{i + len(points)}/{len(rows)}', flush=True)
    print('uploaded', call('GET', f'/collections/{NAME}')['result']['points_count'], 'of', len(rows))


def compare(n=40):
    """The five nearest by Qdrant against the five nearest by the local numpy search (qa_bank's own), for n questions."""
    import numpy as np
    import random
    rows, vectors = bank()
    m = np.asarray(vectors, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    random.seed(5)
    same = 0
    for i in random.sample(range(len(rows)), n):
        q = m[i] + np.random.default_rng(i).normal(0, 0.01, m.shape[1]).astype(np.float32)  # a near rewording
        local = [int(k) for k in np.argsort(-(m @ (q / np.linalg.norm(q))))[:5]]
        cloud = [p['id'] for p in call('POST', f'/collections/{NAME}/points/search', {'vector': q.tolist(), 'limit': 5})['result']]
        same += local[0] == cloud[0]
    print(f'top-1 the same in {same}/{n}')


BOOKS = 'rav_bari_books'


def embed(texts):
    body = json.dumps({'model': 'text-embedding-bge-m3', 'input': texts}).encode()
    req = urllib.request.Request('http://127.0.0.1:1234/v1/embeddings', body, {'Content-Type': 'application/json'})
    return [d['embedding'] for d in json.load(urllib.request.urlopen(req, timeout=300))['data']]


def books():
    units = json.loads((ROOT / 'data/store/book-units.json').read_text())
    names = [c['name'] for c in call('GET', '/collections')['result']['collections']]
    if BOOKS not in names:
        call('PUT', f'/collections/{BOOKS}', {'vectors': {'size': 1024, 'distance': 'Cosine', 'on_disk': True}, 'on_disk_payload': True,
                                               'quantization_config': {'scalar': {'type': 'int8', 'always_ram': True}}})
    start = call('GET', f'/collections/{BOOKS}')['result']['points_count']
    print('books:', len(units), 'units;', start, 'already there', flush=True)
    for i in range(start, len(units), 32):
        batch = units[i:i + 32]
        vectors = embed([(u.get('title', '') + '\n' + u['text'])[:2000] for u in batch])
        points = [{'id': i + j, 'vector': v, 'payload': {'unit': u['id'], 'book': u['book'], 'area': u['area'], 'cite': u['cite'],
                                                         'text': u['text'][:1500]}} for j, (u, v) in enumerate(zip(batch, vectors))]
        call('PUT', f'/collections/{BOOKS}/points?wait=true', {'points': points})
        if i % 3200 == 0:
            print(f'{i + len(points)}/{len(units)}', flush=True)
    print('books uploaded', call('GET', f'/collections/{BOOKS}')['result']['points_count'], 'of', len(units))


if __name__ == '__main__':
    {'upload': upload, 'compare': compare, 'books': books}[sys.argv[1]]()
