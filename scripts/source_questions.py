"""Questions made from a book's own halachot (owner, 2026-10-20: "start from the source instead of searching and
throwing away"): for each halacha, the questions a person would ask that it answers, each answered from it with a verbatim
quotation — the rules of the app's עונג שבת protocol (scripts/halacha/ong-shabbat/PROTOCOL.md in the app), condensed.

  pilot [n]            n halachot (half ילקוט יוסף שבת, half הכשרות למעשה) → data/store/source-pilot.jsonl, for review
  run <area> [...]     every halacha of the areas (shabbat, kashrut, yy-<part>) → appended to the bank's answers.jsonl,
                       then judged by the bank's own `verify` like every answer

Input: data/store/book-units.json (the app's scripts/dump-book-units.mjs). Mechanical checks before anything is kept:
the quotation is a verbatim span of the halacha, the question ends with "?", the answer is short, and the question is
not already in the bank (normalized words). Resumable: a halacha done is recorded in data/store/source-done.json.
"""
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kezohar import config
from kezohar.llm import _post

UNITS = ROOT / 'data/store/book-units.json'
BANK = ROOT / 'data/store/qa-bank/answers.jsonl'
DONE = ROOT / 'data/store/source-done.json'
TOPIC = {'shabbat': 'שבת – לפי ילקוט יוסף', 'kashrut': 'כשרות – הכשרות למעשה'}

SYSTEM = """אתה כותב שאלות ותשובות לאפליקציית הלכה, מתוך הלכה אחת של ספר. לפניך הלכה אחת בלשון הספר.
כתוב 1–3 שאלות שאדם רגיל באמת שואל ושההלכה הזו עונה עליהן במפורש — מעשיות, במילים של היום ("מקרר", "פלטה",
"מגבון לח"), קצרות (עד 16 מילים), כל אחת מסתיימת ב"?". השאלה עוסקת בדיוק במה שההלכה פוסקת עליו — לא בדבר אחר שמוזכר
בה רק כדוגמה או כהשוואה. לא שאלה על מושג מופשט ולא שאלה שההלכה לא עונה עליה במלואה.
לכל שאלה:
- answer: עונה בדיוק על השאלה שנשאלה, 1–2 משפטים פשוטים (עד 260 תווים) שאינם אומרים דבר שהספר אינו אומר. שמור בדיוק על רמת הספר: "טוב / ראוי /
  יש להחמיר / לכתחילה / נוהגים" לא הופכים ל"אסור" או "חייב"; "מותר" לא הופך ל"מצוה"; כל תנאי נשאר (אם…, רק…, בתנאי…,
  לכתחילה/בדיעבד). אל תכליל מקרה פרטי לכלל. בלי דעות אחרות, בלי עצות משלך, בלי "לפי הספר".
- quote: קטע רציף מתוך טקסט ההלכה, מילה במילה בדיוק (25–500 תווים, בלי השמטות ובלי שינויים), שמכיל את מה שהתשובה אומרת.
אם ההלכה אינה מעשית (הקדמה, טעם, רשימת מקורות, הפניה) — החזר רשימה ריקה. JSON בלבד."""
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['question', 'answer', 'quote'],
    'properties': {'question': {'type': 'string'}, 'answer': {'type': 'string'}, 'quote': {'type': 'string'}}}}}}


def norm(text):
    return ' '.join(re.sub(r'[^א-ת ]', ' ', text).split())


def flat(text):
    return ' '.join(str(text).split())


def make(unit):
    body = {'model': config.llm_model(), 'temperature': 0.2, 'max_tokens': 1500, 'stream': False, '_prefer_strong': True,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'qa', 'strict': True, 'schema': SCHEMA}},
            'messages': [{'role': 'system', 'content': SYSTEM},
                         {'role': 'user', 'content': f"{unit['title']}\n{unit['text']}"}]}
    try:
        items = json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=90)['choices'][0]['message']['content'])['items']
    except Exception:
        return unit, None
    text = flat(unit['text'])
    kept = []
    for it in items:
        q, a, quote = it['question'].strip(), it['answer'].strip(), flat(it['quote']).strip(' "״')
        if not q.endswith('?') or len(q.split()) > 20 or len(a) > 300 or len(quote) < 20 or quote not in text:
            continue
        kept.append({'q': q, 'answer': a, 'quote': quote, 'cite': unit['cite'], 'unit': unit['id']})
    return unit, kept


def existing():
    seen = set()
    for line in BANK.read_text().splitlines():
        seen.add(norm(json.loads(line)['q']))
    app = ROOT / 'data/store/all-questions.json'
    if app.exists():
        seen |= {norm(r['question']) for r in json.loads(app.read_text())}
    return seen


def pilot(n=100):
    units = json.loads(UNITS.read_text())
    random.seed(11)
    pick = random.sample([u for u in units if u['area'] == 'shabbat'], n // 2) + random.sample([u for u in units if u['area'] == 'kashrut'], n - n // 2)
    seen = existing()
    out = (ROOT / 'data/store/source-pilot.jsonl').open('w')
    made = skipped = dup = 0
    with ThreadPoolExecutor(6) as pool:
        for unit, kept in pool.map(make, pick):
            if not kept:
                skipped += 1
                continue
            for r in kept:
                if norm(r['q']) in seen:
                    dup += 1
                    continue
                seen.add(norm(r['q']))
                made += 1
                out.write(json.dumps(dict(r, area=unit['area'], text=unit['text']), ensure_ascii=False) + '\n')
    print(f'pilot: {len(pick)} halachot → {made} questions; {skipped} halachot gave none; {dup} already in the bank', flush=True)


def run(areas):
    units = [u for u in json.loads(UNITS.read_text()) if u['area'] in areas]
    done = set(json.loads(DONE.read_text())) if DONE.exists() else set()
    todo = [u for u in units if u['id'] not in done]
    seen = existing()
    made = 0
    with BANK.open('a') as bank, ThreadPoolExecutor(6) as pool:
        for i, (unit, kept) in enumerate(pool.map(make, todo)):
            if kept is None:
                continue  # the model failed: tried again on the next run
            for r in kept:
                if norm(r['q']) in seen:
                    continue
                seen.add(norm(r['q']))
                made += 1
                bank.write(json.dumps({'topic': TOPIC.get(unit['area'], 'ילקוט יוסף'), 'q': r['q'], 'sourced': True, 'answer': r['answer'],
                                       'quote': r['quote'], 'cite': r['cite'], 'mode': 'source-first'}, ensure_ascii=False) + '\n')
            done.add(unit['id'])
            if i % 50 == 0:
                bank.flush()
                DONE.write_text(json.dumps(sorted(done)))
                print(f'{i}/{len(todo)} halachot, {made} questions', flush=True)
    DONE.write_text(json.dumps(sorted(done)))
    print(f'source run done: {made} questions from {len(todo)} halachot', flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'pilot':
        pilot(int(sys.argv[2]) if len(sys.argv) > 2 else 100)
    elif sys.argv[1] == 'run':
        run(set(sys.argv[2:]))
