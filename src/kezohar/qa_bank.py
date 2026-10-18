"""The ready answer bank (owner, 2026-10-16): source-based answers prepared in advance (scripts/build_qa_bank.py).

A question almost identical in meaning to a bank question (cosine ≥ THRESHOLD on bge-m3, the library's model) gets its
prepared answer at once. The bar is high on purpose: in halacha a small detail changes the answer, so only a near
restatement of the same question is answered from the bank; anything else takes the full path.
"""
import json
import threading
from pathlib import Path
from . import config

THRESHOLD = 0.95
_lock = threading.Lock()
_bank = None
_matrix = None


def _load(model):
    path = Path(config.get('QA_BANK', 'data/store/qa-bank/answers.jsonl'))
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    # An answer that talks about "the passage" instead of answering is left out (the prompt forbids it; some slipped).
    rows = [r for r in rows if r.get('answer') and 'הקטע' not in r['answer']]
    # Only answers the strong model judged right (scripts/build_qa_bank.py verify; owner, 2026-10-18: "only what passed
    # the check — the source does not matter as long as the answer is right").
    checks = path.with_name('checks.jsonl')
    import hashlib
    good = {r['key'] for r in map(json.loads, checks.read_text().splitlines()) if r['ok']} if checks.exists() else set()
    rows = [r for r in rows if hashlib.sha256((r['q'] + '|' + r['answer']).encode()).hexdigest()[:20] in good]
    if not rows:
        return [], []
    # The questions as people ask them (scripts/build_qa_bank.py wording): matched in their new wording.
    wording = path.with_name('wording.jsonl')
    new = {r['old']: r['new'] for r in map(json.loads, wording.read_text().splitlines())} if wording.exists() else {}
    rows = [dict(r, q=new.get(r['q'], r['q'])) for r in rows]
    # Question vectors are kept beside the bank (keyed by the question), so a restart embeds only new ones.
    cache_path = path.with_suffix('.vectors.json')
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = [r['q'] for r in rows if r['q'] not in cache]
    for i in range(0, len(todo), 16):  # the embedding client takes at most 16 texts a call
        for q, v in zip(todo[i:i + 16], model.embed_many(todo[i:i + 16])):
            cache[q] = [round(float(x), 5) for x in v]
    if todo:
        cache_path.write_text(json.dumps(cache))
    return rows, [cache[r['q']] for r in rows]


def lookup(question, model):
    """The prepared answer for a near restatement of a bank question, or None."""
    global _bank
    if config.get('QA_BANK_LOOKUP', '1') == '0' or model is None:
        return None
    with _lock:
        if _bank is None:
            try:
                _bank = _load(model)
            except Exception:
                _bank = ([], [])
    rows, vectors = _bank
    if not rows:
        return None
    # One matrix product over the whole bank (numpy) instead of 7,000 Python cosines: 0.7 s → a few ms.
    import numpy as np
    global _matrix
    if _matrix is None or _matrix.shape[0] != len(vectors):
        m = np.asarray(vectors, dtype=np.float32)
        _matrix = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    qv = np.asarray(model.embed_query(question), dtype=np.float32)
    scores = _matrix @ (qv / max(float(np.linalg.norm(qv)), 1e-9))
    i = int(scores.argmax())
    best, row = float(scores[i]), rows[i]
    if best < THRESHOLD:
        return None
    if not (row.get('quote') and row.get('cite')):  # checked right, with no source found: labelled so (owner, 2026-10-16)
        return {'verdict': 'model_knowledge', 'mode': 'model-knowledge', 'sources': [], 'halachic_verified': False,
                'answer': row['answer'], 'bari': {'answer': row['answer'], 'quote': None, 'cite': None, 'source': 'model'},
                'qa_bank': {'question': row['q'], 'similarity': round(best, 3)}}
    return {'verdict': 'ok', 'mode': 'summary-with-quote', 'sources': [{'reference': row['cite']}], 'halachic_verified': False,
            'answer': row['answer'] + '\n\nמקור: ״' + row['quote'] + '״ (' + row['cite'] + ').',
            'bari': {'answer': row['answer'], 'quote': row['quote'], 'cite': row['cite'], 'source': 'library'},
            'qa_bank': {'question': row['q'], 'similarity': round(best, 3)}}
