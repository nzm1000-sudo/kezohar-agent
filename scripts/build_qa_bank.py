"""Build the source-based answer bank (owner, 2026-10-16: grow from ~3,200 to ~5,000 questions).

Stage 1 `questions`: the model writes questions per topic; duplicates of each other and of the app's 3,232 verified
questions are dropped (normalised text). Stage 2 `answers`: each question goes through the agent's full path; only
answers with a source quotation are kept, labelled "מבוססת מקור". Resumable: rerun to continue.

Usage: build_qa_bank.py questions | answers [--limit N]
Output: data/store/qa-bank/questions.jsonl, data/store/qa-bank/answers.jsonl (ignored, never published).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
OUT = ROOT / 'data/store/qa-bank'

TOPICS = [
    'שבת – מלאכות ובישול', 'שבת – מוקצה וטלטול', 'שבת – עירוב והוצאה', 'שבת – קידוש, סעודות והבדלה',
    'ברכות הנהנין', 'ברכה אחרונה וברכת המזון', 'ברכות הראייה והשבח', 'תפילת שחרית', 'מנחה וערבית',
    'קריאת שמע ותפילין', 'ציצית ומזוזה', 'בית הכנסת וקריאת התורה', 'כשרות – בשר וחלב', 'כשרות – הכשרת כלים וטבילת כלים',
    'פסח – חמץ, מצה וסדר', 'ראש השנה ויום כיפור', 'סוכות ושמחת תורה', 'חנוכה', 'פורים', 'ספירת העומר ושבועות',
    'תעניות ובין המצרים', 'ראש חודש', 'אבלות ומנהגי אבלות', 'כיבוד הורים', 'צדקה ומעשרות', 'לשון הרע ובין אדם לחברו',
    'חומש בראשית – אישים ואירועים', 'חומש שמות – אישים ואירועים', 'במדבר ודברים – אישים ואירועים', 'נביאים ראשונים',
    'נביאים אחרונים', 'כתובים – תהילים, משלי, איוב, מגילות', 'משנה ותלמוד – מושגים ותנאים', 'אמוראים וגאונים',
    'ראשונים ואחרונים – אישים וספרים', 'מושגים בהלכה ובאמונה', 'קבלה וחסידות – מושגים', 'מנהגי עדות המזרח',
    'בית המקדש והקרבנות', 'היסטוריה יהודית ומועדים בלוח',
]

PROMPT = ('כתוב {n} שאלות ביהדות בנושא: {topic}. שאלות שאנשים באמת שואלים — מעשיות, עובדתיות ומושגיות, מגוונות, '
          'כל אחת שאלה אחת ברורה בעברית (עד 15 מילים), בלי מספור. לא שאלות אישיות רגישות ולא שאלות שתשובתן תלויה '
          'בפרטי מקרה. החזר JSON בלבד.')
SCHEMA = {'type': 'object', 'properties': {'questions': {'type': 'array', 'items': {'type': 'string'}}},
          'required': ['questions'], 'additionalProperties': False}


def norm(q):
    import re
    from kezohar.hebrew import normalize
    return re.sub(r'[^א-ת ]', '', normalize(q)).strip()


def questions(per_topic=55):
    from kezohar import config
    from kezohar.llm import _post
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'questions.jsonl'
    seen = {norm(q) for q in json.loads((ROOT / 'data/store/app-questions.json').read_text())}
    done_topics = set()
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            seen.add(norm(row['q']))
            done_topics.add(row['topic'])
    with path.open('a') as out:
        for topic in TOPICS:
            if topic in done_topics:
                continue
            body = {'model': config.llm_model(), 'temperature': 0.7, 'max_tokens': 3000, 'stream': False,
                    'response_format': {'type': 'json_schema', 'json_schema': {'name': 'questions', 'strict': True, 'schema': SCHEMA}},
                    'messages': [{'role': 'user', 'content': PROMPT.format(n=per_topic, topic=topic)}]}
            try:
                got = json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=90)['choices'][0]['message']['content'])['questions']
            except Exception as exc:
                print('topic failed', topic, type(exc).__name__, flush=True)
                continue
            kept = 0
            for q in got:
                q = ' '.join(str(q).split())
                if 6 <= len(q) <= 160 and norm(q) not in seen:
                    seen.add(norm(q))
                    out.write(json.dumps({'topic': topic, 'q': q}, ensure_ascii=False) + '\n')
                    kept += 1
            out.flush()
            print(f'{topic}: {kept}', flush=True)


SUB_PROMPT = 'פרק את הנושא "{topic}" ביהדות ל-{n} תתי-נושאים מובחנים ומעשיים (שמות קצרים). החזר JSON.'
SUB_SCHEMA = {'type': 'object', 'properties': {'subtopics': {'type': 'array', 'items': {'type': 'string'}}},
              'required': ['subtopics'], 'additionalProperties': False}


def subtopics(per_sub=30, n_subs=12):
    """Round two (owner, 2026-10-16: beyond 5,000): each topic split into ~6 subtopics, ~30 new questions each."""
    from kezohar import config
    from kezohar.llm import _post
    path = OUT / 'questions.jsonl'
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    seen = {norm(q) for q in json.loads((ROOT / 'data/store/app-questions.json').read_text())} | {norm(r['q']) for r in rows}
    done = {r['topic'] for r in rows}
    with path.open('a') as out:
        for topic in TOPICS:
            body = {'model': config.llm_model(), 'temperature': 0, 'max_tokens': 400, 'stream': False,
                    'response_format': {'type': 'json_schema', 'json_schema': {'name': 'subtopics', 'strict': True, 'schema': SUB_SCHEMA}},
                    'messages': [{'role': 'user', 'content': SUB_PROMPT.format(topic=topic, n=n_subs)}]}
            try:
                subs = json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=60)['choices'][0]['message']['content'])['subtopics'][:n_subs]
            except Exception:
                continue
            for sub in subs:
                label = f'{topic} › {sub}'
                if label in done:
                    continue
                body = {'model': config.llm_model(), 'temperature': 0.7, 'max_tokens': 2500, 'stream': False,
                        'response_format': {'type': 'json_schema', 'json_schema': {'name': 'questions', 'strict': True, 'schema': SCHEMA}},
                        'messages': [{'role': 'user', 'content': PROMPT.format(n=per_sub, topic=label)}]}
                try:
                    got = json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=90)['choices'][0]['message']['content'])['questions']
                except Exception:
                    continue
                kept = 0
                for q in got:
                    q = ' '.join(str(q).split())
                    if 6 <= len(q) <= 160 and norm(q) not in seen:
                        seen.add(norm(q))
                        out.write(json.dumps({'topic': label, 'q': q}, ensure_ascii=False) + '\n')
                        kept += 1
                out.flush()
                print(f'{label}: {kept}', flush=True)


WORKERS = 3


def answers(limit=None):
    from kezohar.demo import demo_agent
    from kezohar.request_budget import RequestBudget
    agent = demo_agent()
    qpath, apath = OUT / 'questions.jsonl', OUT / 'answers.jsonl'
    done = {json.loads(l)['q'] for l in apath.read_text().splitlines()} if apath.exists() else set()
    todo = [json.loads(l) for l in qpath.read_text().splitlines() if json.loads(l)['q'] not in done]
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()
    count = {'tried': 0, 'kept': 0}

    def one(row):
        started = time.time()
        try:
            r = agent.converse(row['q'], request_budget=RequestBudget(seconds=90, max_context_bytes=48000), timeout=45, cache_ttl=0)
        except Exception as exc:
            r = {'verdict': 'error', 'error': type(exc).__name__}
        bari = r.get('bari') or {}
        sourced = bool(bari.get('answer') and bari.get('quote') and bari.get('cite'))
        line = json.dumps({'topic': row['topic'], 'q': row['q'], 'sourced': sourced, 'answer': bari.get('answer'),
                           'quote': bari.get('quote'), 'cite': bari.get('cite'), 'mode': r.get('mode'),
                           'seconds': round(time.time() - started, 1)}, ensure_ascii=False) + '\n'
        with lock:  # one writer at a time: each answer stays one whole line
            out.write(line)
            out.flush()
            count['tried'] += 1
            count['kept'] += sourced
            if count['tried'] % 25 == 0:
                print(f"{count['tried']} tried, {count['kept']} sourced", flush=True)

    # Three questions at a time (owner, 2026-10-17): one by one took ~10 s a question, a day and a half for a round.
    with apath.open('a') as out, ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, todo[:limit]))
    tried, kept = count['tried'], count['kept']
    print(f'done: {tried} tried, {kept} sourced', flush=True)


CHECK_SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}, 'why': {'type': 'string'}},
                'required': ['ok', 'why'], 'additionalProperties': False}
CHECK_PROMPT = ('אתה בודק תשובות במאגר שאלות ביהדות. ok=true רק אם כל אלה מתקיימים: (1) התשובה עונה ישירות ובמלואו על השאלה, '
                'בלי לדבר על "הקטע" או "המקור" במקום לענות; (2) היא נכונה לפי ההלכה והעובדות המקובלות (בהלכה — לפי מרן '
                'השולחן ערוך ופוסקי ספרד, או שהיא מציינת למי הדין); (3) אם יש ציטוט — הוא עוסק באותו עניין ותומך בעיקר התשובה; '
                '(4) הניסוח ברור ולא סותר את עצמו. בכל ספק — ok=false. why: משפט קצר. החזר JSON בלבד.')


def key_of(row):
    import hashlib
    return hashlib.sha256((row['q'] + '|' + (row.get('answer') or '')).encode()).hexdigest()[:20]


def checks():
    """{key_of(row): ok} from checks.jsonl — written by `verify`, beside the bank so the answer stages never race it."""
    path = OUT / 'checks.jsonl'
    return {r['key']: r['ok'] for r in map(json.loads, path.read_text().splitlines())} if path.exists() else {}


def verify():
    """Every answer judged by the strong cloud model (owner, 2026-10-17: "checked questions"; 2026-10-18: a source is not
    required when the answer is right); the bank and the app use only answers judged ok. Resumable."""
    from concurrent.futures import ThreadPoolExecutor
    from kezohar import config
    from kezohar.llm import _post
    done = checks()
    rows = [r for r in map(json.loads, (OUT / 'answers.jsonl').read_text().splitlines())
            if r.get('answer') and key_of(r) not in done]

    def judge(row):
        body = {'model': config.llm_model(), 'temperature': 0, 'max_tokens': 120, 'stream': False,
                'response_format': {'type': 'json_schema', 'json_schema': {'name': 'check', 'strict': True, 'schema': CHECK_SCHEMA}},
                'messages': [{'role': 'system', 'content': CHECK_PROMPT},
                             {'role': 'user', 'content': f"שאלה: {row['q']}\nתשובה: {row['answer']}\nציטוט: {row.get('quote') or 'אין'}\nמקור: {row.get('cite') or 'אין'}"}]}
        try:
            got = json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=40)['choices'][0]['message']['content'])
            return {'key': key_of(row), 'q': row['q'], 'ok': bool(got['ok']), 'why': got.get('why', '')}
        except Exception:
            return None

    good = bad = 0
    with (OUT / 'checks.jsonl').open('a') as out, ThreadPoolExecutor(4) as pool:
        for got in pool.map(judge, rows):
            if got:
                out.write(json.dumps(got, ensure_ascii=False) + '\n')
                out.flush()
                good += got['ok']
                bad += not got['ok']
                if (good + bad) % 100 == 0:
                    print(f'{good} ok, {bad} rejected', flush=True)
    print(f'verify done: {good} ok, {bad} rejected', flush=True)


def repair():
    """Answers the check rejected are answered again (owner, 2026-10-17: the question stays, only the answer is redone).
    Run when no other stage writes answers.jsonl; the new answers are checked by the next `verify`."""
    from kezohar.demo import demo_agent
    from kezohar.request_budget import RequestBudget
    agent = demo_agent()
    verdict = checks()
    apath = OUT / 'answers.jsonl'
    rows = [json.loads(l) for l in apath.read_text().splitlines()]
    fixed = 0
    for i, row in enumerate(rows):
        if not row.get('answer') or verdict.get(key_of(row)) is not False:
            continue
        try:
            r = agent.converse(row['q'], request_budget=RequestBudget(seconds=90, max_context_bytes=48000), timeout=45, cache_ttl=0)
        except Exception:
            continue
        bari = r.get('bari') or {}
        if bari.get('answer') and bari['answer'] != row['answer']:
            rows[i] = {**row, 'sourced': bool(bari.get('quote') and bari.get('cite')), 'answer': bari['answer'],
                       'quote': bari.get('quote'), 'cite': bari.get('cite'), 'mode': r.get('mode')}
            fixed += 1
            if fixed % 25 == 0:
                apath.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows))
    apath.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows))
    print('repair done:', fixed, flush=True)


# Each fix names the question it fixes, word for word: a fix is kept only when that text is exactly the question asked
# (2026-10-18: by index alone, 12% of the fixes landed on a neighbouring question).
WORDING_SCHEMA = {'type': 'object', 'properties': {'fixes': {'type': 'array', 'items': {'type': 'object', 'properties': {
    'original': {'type': 'string'}, 'q': {'type': 'string'}}, 'required': ['original', 'q'], 'additionalProperties': False}}},
    'required': ['fixes'], 'additionalProperties': False}
WORDING_PROMPT = ('אתה עורך לשון. לפניך שאלות ביהדות ממאגר. תקן שאלה שניסוחה אינו טבעי, מסורבל, כפול או אינו כפי שאדם '
                  'שואל בעברית של היום — קצר, פשוט וברור. דוגמאות: "מה מברכים על ריח של עשבי בשמים?" -> "מה מברכים על עשבים '
                  'ריחניים?"; "מה ביקש המן להכין למרדכי?" -> "מה הכין המן למרדכי?"; "מהו כלל הלכתי ומה ההבדל בינו לבין '
                  'פסיקה?" -> "מה ההבדל בין כלל הלכתי לפסק הלכה?". שם ברכה או נוסח שייך לתשובה, לא לשאלה. שמור בדיוק על '
                  'משמעות השאלה ועל כל פרט בה; אל תוסיף ואל תשמיט פרטים; מונחים הלכתיים נכונים נשארים. שאלה טובה — אל '
                  'תחזיר אותה. החזר JSON: fixes = [{original, q}] רק לשאלות שתוקנו — original הוא נוסח השאלה המקורי מילה במילה.')


def wording():
    """Questions worded as people ask them (owner, 2026-10-17): the strong model rewrites only unnatural or imprecise
    wording, meaning kept. Written to wording.jsonl ({old, new}); the bank and the app read the new wording."""
    from concurrent.futures import ThreadPoolExecutor
    from kezohar import config
    from kezohar.llm import _post
    path = OUT / 'wording.jsonl'
    seen = {json.loads(l)['old'] for l in path.read_text().splitlines()} if path.exists() else set()
    done_path = OUT / 'wording.checked'
    checked = set(done_path.read_text().splitlines()) if done_path.exists() else set()
    qs = [json.loads(l)['q'] for l in (OUT / 'questions.jsonl').read_text().splitlines()]
    todo = [q for q in dict.fromkeys(qs) if q not in seen and q not in checked]
    batches = [todo[i:i + 10] for i in range(0, len(todo), 10)]

    def one(batch):
        listing = '\n'.join(batch)
        body = {'model': config.llm_model(), 'temperature': 0, 'max_tokens': 1500, 'stream': False,
                'response_format': {'type': 'json_schema', 'json_schema': {'name': 'wording', 'strict': True, 'schema': WORDING_SCHEMA}},
                'messages': [{'role': 'system', 'content': WORDING_PROMPT}, {'role': 'user', 'content': listing}]}
        try:
            fixes = json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=60)['choices'][0]['message']['content'])['fixes']
        except Exception:
            return batch, None
        asked = set(batch)
        return batch, [(f['original'].strip(), ' '.join(f['q'].split())) for f in fixes
                       if f['original'].strip() in asked and f['q'].strip() and f['q'].strip() != f['original'].strip()]

    changed = 0
    with path.open('a') as out, done_path.open('a') as ok, ThreadPoolExecutor(3) as pool:
        for batch, fixes in pool.map(one, batches):
            if fixes is None:
                continue
            for old, new in fixes:
                out.write(json.dumps({'old': old, 'new': new}, ensure_ascii=False) + '\n')
                changed += 1
            ok.write('\n'.join(batch) + '\n')
            out.flush(); ok.flush()
    print(f'wording done: {changed} reworded of {len(todo)}', flush=True)


def reworded():
    """{old question: new wording}."""
    path = OUT / 'wording.jsonl'
    return {r['old']: r['new'] for r in map(json.loads, path.read_text().splitlines())} if path.exists() else {}


def rekashrut():
    """Kashrut questions answered again with the bank off, so they come from הכשרות למעשה (owner, 2026-10-17)."""
    import os
    os.environ['QA_BANK_LOOKUP'] = '0'
    from kezohar.agent import _KASHRUT
    from kezohar.demo import demo_agent
    from kezohar.request_budget import RequestBudget
    agent = demo_agent()
    apath = OUT / 'answers.jsonl'
    rows = [json.loads(l) for l in apath.read_text().splitlines()]
    changed = 0
    for i, row in enumerate(rows):
        if 'הכשרות למעשה' in (row.get('cite') or '') or not (_KASHRUT.search(row['q']) or row['topic'].startswith('כשרות')):
            continue
        try:
            r = agent.converse(row['q'], request_budget=RequestBudget(seconds=90, max_context_bytes=48000), timeout=45, cache_ttl=0)
        except Exception:
            continue
        bari = r.get('bari') or {}
        if bari.get('answer') and bari.get('quote') and bari.get('cite'):
            rows[i] = {**row, 'sourced': True, 'answer': bari['answer'], 'quote': bari['quote'], 'cite': bari['cite'], 'mode': r.get('mode')}
            changed += 1
        if changed and changed % 25 == 0:
            apath.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows))
    apath.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows))
    print('rekashrut done:', changed, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['questions', 'subtopics', 'answers', 'rekashrut', 'verify', 'repair', 'wording'])
    p.add_argument('--limit', type=int)
    a = p.parse_args()
    {'questions': questions, 'subtopics': subtopics, 'rekashrut': rekashrut, 'verify': verify, 'repair': repair, 'wording': wording}.get(a.stage, lambda: answers(a.limit))()
