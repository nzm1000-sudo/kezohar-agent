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


def answers(limit=None):
    from kezohar.demo import demo_agent
    from kezohar.request_budget import RequestBudget
    agent = demo_agent()
    qpath, apath = OUT / 'questions.jsonl', OUT / 'answers.jsonl'
    done = {json.loads(l)['q'] for l in apath.read_text().splitlines()} if apath.exists() else set()
    todo = [json.loads(l) for l in qpath.read_text().splitlines() if json.loads(l)['q'] not in done]
    kept = tried = 0
    with apath.open('a') as out:
        for row in todo[:limit]:
            tried += 1
            started = time.time()
            try:
                r = agent.converse(row['q'], request_budget=RequestBudget(seconds=90, max_context_bytes=48000), timeout=45, cache_ttl=0)
            except Exception as exc:
                r = {'verdict': 'error', 'error': type(exc).__name__}
            bari = r.get('bari') or {}
            sourced = bool(bari.get('answer') and bari.get('quote') and bari.get('cite'))
            out.write(json.dumps({'topic': row['topic'], 'q': row['q'], 'sourced': sourced, 'answer': bari.get('answer'),
                                  'quote': bari.get('quote'), 'cite': bari.get('cite'), 'mode': r.get('mode'),
                                  'seconds': round(time.time() - started, 1)}, ensure_ascii=False) + '\n')
            out.flush()
            kept += sourced
            if tried % 25 == 0:
                print(f'{tried} tried, {kept} sourced', flush=True)
    print(f'done: {tried} tried, {kept} sourced', flush=True)


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
    p.add_argument('stage', choices=['questions', 'subtopics', 'answers', 'rekashrut'])
    p.add_argument('--limit', type=int)
    a = p.parse_args()
    {'questions': questions, 'subtopics': subtopics, 'rekashrut': rekashrut}.get(a.stage, lambda: answers(a.limit))()
