"""The bank's sourced questions for the app's "מאגר השאלות" (owner, 2026-10-17): question and subject only — the answer
stays on the agent; only answers judged ok by `build_qa_bank.py verify`; tapping a question asks it, and the bank answers a near restatement at once.

Usage: export_bank_questions.py <app>/public/data/rav-bari-questions.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_qa_bank import checks, key_of
ok = {k for k, v in checks().items() if v}
rows = [json.loads(l) for l in (ROOT / 'data/store/qa-bank/answers.jsonl').read_text().splitlines()]
seen, out = set(), []
for r in rows:
    if r.get('sourced') and key_of(r) in ok and 'הקטע' not in (r.get('answer') or '') and r['q'] not in seen:
        seen.add(r['q'])
        out.append([r['topic'].split(' › ')[0].strip(), r['q']])
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
print(len(out), 'questions')
