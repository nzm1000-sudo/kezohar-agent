"""Answers readers called טעות (data/store/answer-ratings.jsonl), newest first, with how many called the same one right.

Usage: review_ratings.py [days]   — default: the last 7 days
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROWS = Path(__file__).resolve().parents[1] / 'data/store/answer-ratings.jsonl'
days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - days * 86400))
rows = [json.loads(line) for line in ROWS.read_text().splitlines() if line.strip()] if ROWS.exists() else []
rows = [r for r in rows if r.get('at', '') >= since]
right = Counter(r['question'] for r in rows if r['verdict'] == 'right')
wrong = [r for r in rows if r['verdict'] == 'wrong']
print(f'{len(rows)} דירוגים ב־{days} ימים · {len(wrong)} טעות')
for r in reversed(wrong):
    tag = (' · ' + r['id'] if r.get('id') else '') + (f" · {right[r['question']]} נכון" if right[r['question']] else '')
    print(f"\n[{r['at']}] {r['kind']}{tag}")
    print('  ש:', r['question'])
    print('  ת:', r['answer'][:300])
