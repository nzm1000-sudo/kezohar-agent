"""A second look at the family-purity and modesty questions (2026-10-21): only those that belong to women's laws, family
purity, modesty or marriage, with a whole, clear answer that does not turn a particular case into a general rule, are
kept. The rest are listed in data/store/qa-bank/dropped.json, which the bank's export leaves out."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from question_taxonomy import call
from build_qa_bank import key_of

OUT = ROOT / 'data/store/qa-bank'
good = {r['key'] for r in map(json.loads, (OUT / 'checks.jsonl').read_text().splitlines()) if r['ok']}
rows = [r for r in map(json.loads, (OUT / 'answers.jsonl').read_text().splitlines())
        if r.get('mode') == 'source-first' and ('טהרת המשפחה' in r['topic'] or 'צניעות' in r['topic']) and key_of(r) in good]
schema = {'type': 'object', 'additionalProperties': False, 'required': ['keep', 'why'],
          'properties': {'keep': {'type': 'boolean'}, 'why': {'type': 'string'}}}
SYSTEM = ('בדוק שאלה ותשובה למאגר "הלכות נשים" באפליקציית הלכה. keep=true רק אם שני אלה נכונים: (1) השאלה שייכת להלכות '
          'נשים, טהרת המשפחה, צניעות, או חיי הזוגיות והבית — לא מוסר כללי ולא נושא אחר; (2) התשובה שלמה, ברורה ונכונה '
          'לשאלה, בלשון עדינה, ואינה הופכת מקרה מסוים לכלל כללי מטעה. JSON בלבד.')


def judge(r):
    try:
        g = call(SYSTEM, f"שאלה: {r['q']}\nתשובה: {r['answer']}\nלשון המקור: {r.get('quote', '')}", schema, 'gentle', 200, timeout=60)
        return r['q'], g['keep'], g['why']
    except Exception:
        return r['q'], False, 'not judged'
dropped = json.loads((OUT / 'dropped.json').read_text()) if (OUT / 'dropped.json').exists() else {}
kept = 0
with ThreadPoolExecutor(6) as pool:
    for q, keep, why in pool.map(judge, rows):
        if keep:
            kept += 1
        else:
            dropped[q] = why
(OUT / 'dropped.json').write_text(json.dumps(dropped, ensure_ascii=False, indent=1))
print(f'gentle review: {len(rows)} judged, {kept} kept, {len(rows) - kept} left out')
