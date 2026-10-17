"""The bank's sourced questions for the app's "מאגר השאלות" (owner, 2026-10-17): question and subject only — the answer
stays on the agent; every answered question (owner, 2026-10-17: a question is never dropped — a rejected answer is redone by `repair`, and
meanwhile the agent answers it on the full path); tapping a question asks it, and the bank answers a near restatement at once.

Usage: export_bank_questions.py <app>/public/data/rav-bari-questions.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = [json.loads(l) for l in (ROOT / 'data/store/qa-bank/answers.jsonl').read_text().splitlines()]
seen, out = set(), []
for r in rows:
    if r.get('answer') and r['q'] not in seen:
        seen.add(r['q'])
        out.append([r['topic'].split(' › ')[0].strip(), r['q']])
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
print(len(out), 'questions')
