"""Run data/eval/heldout_50.json against the loopback demo and score coarsely.

answered: verdict delivered an answer; hit: an expected keyword group appears.
Declines on answerable questions and answers on unanswerable ones are misses.
Results: data/store/heldout-eval/<label>.json (ignored, never published).
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECLINE = {'knowledge_insufficient', 'no_source', 'insufficient', 'blocked', 'clarify', 'error'}


def ask(question, url='http://127.0.0.1:8711/demo/ask'):
    req = urllib.request.Request(url, data=json.dumps({'question': question, 'top_k': 5}, ensure_ascii=False).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)
    except Exception as exc:
        return {'verdict': 'error', 'error': type(exc).__name__, 'answer': ''}


def score(item, result):
    answer = result.get('answer') or ''
    answered = result.get('verdict') not in DECLINE and bool(answer.strip())
    if item.get('answerable', True) is False:
        return {'answered': answered, 'correct': not answered}
    import re
    plain = re.sub(r'[\u0591-\u05C7]', '', answer).replace('"', '״').replace("''", '״')
    hit = all(any(k.replace('"', '״') in plain for k in group) for group in item['expect_any'])
    return {'answered': answered, 'hit': hit, 'correct': answered and hit}


def main(label):
    items = json.loads((ROOT / 'data/eval/heldout_50.json').read_text())['questions']
    out = ROOT / 'data/store/heldout-eval' / (label + '.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in items:
        t = time.perf_counter(); result = ask(item['q']); wall = round(time.perf_counter() - t, 2)
        rows.append({**item, 'wall_s': wall, 'verdict': result.get('verdict'), 'answer': result.get('answer'),
                     'sources': [s.get('reference') for s in result.get('sources', [])][:5], **score(item, result)})
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(item['id'], wall, rows[-1]['verdict'], 'OK' if rows[-1]['correct'] else 'MISS', flush=True)
    by = {}
    for r in rows: by.setdefault(r['domain'], []).append(r['correct'])
    summary = {'label': label, 'correct': sum(r['correct'] for r in rows), 'total': len(rows),
               'answered': sum(r['answered'] for r in rows),
               'median_wall_s': sorted(r['wall_s'] for r in rows)[len(rows) // 2],
               'by_domain': {d: f'{sum(v)}/{len(v)}' for d, v in by.items()}}
    out.with_suffix('.summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'run')
