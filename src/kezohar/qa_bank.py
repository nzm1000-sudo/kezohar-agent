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


def _load(model):
    path = Path(config.get('QA_BANK', 'data/store/qa-bank/answers.jsonl'))
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    # An answer that talks about "the passage" instead of answering is left out (the prompt forbids it; some slipped).
    rows = [r for r in rows if r.get('sourced') and r.get('answer') and r.get('quote') and r.get('cite') and 'הקטע' not in r['answer']]
    # Answers the strong model rejected are left out (scripts/build_qa_bank.py verify); while a check is still running,
    # an unchecked answer stays.
    checks = path.with_name('checks.jsonl')
    if checks.exists():
        import hashlib
        rejected = {r['key'] for r in map(json.loads, checks.read_text().splitlines()) if not r['ok']}
        rows = [r for r in rows if hashlib.sha256((r['q'] + '|' + r['answer']).encode()).hexdigest()[:20] not in rejected]
    if not rows:
        return [], []
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
    from .vector import cosine
    qv = model.embed_query(question)
    best, row = max(((cosine(qv, v), r) for v, r in zip(vectors, rows)), key=lambda pair: pair[0])
    if best < THRESHOLD:
        return None
    return {'verdict': 'ok', 'mode': 'summary-with-quote', 'sources': [{'reference': row['cite']}], 'halachic_verified': False,
            'answer': row['answer'] + '\n\nמקור: ״' + row['quote'] + '״ (' + row['cite'] + ').',
            'bari': {'answer': row['answer'], 'quote': row['quote'], 'cite': row['cite'], 'source': 'library'},
            'qa_bank': {'question': row['q'], 'similarity': round(best, 3)}}
