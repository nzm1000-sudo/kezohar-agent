"""The questions bank by meaning (owner, 2026-10-20): each category's subjects, and each question's subject and kind.

  build [cat ...]   the model proposes the category's subjects from a sample, then every question is assigned one
  update            only the questions not yet assigned (new bank answers), to the subjects already there
  export <out>      the app's file (public/data/question-taxonomy.json): {cat: {topics, kinds, of: {question: [t, k]}}}

Input: data/store/all-questions.json ([{category, topic, question}], the app's scripts/dump-questions.mjs).
Kept in data/store/question-taxonomy.json. The order shown in the app is alphabetical there, not here.
Assignment: 20 questions a call; each answer echoes the question's first two words, so a misplaced index is dropped and
asked again; what is left is asked one by one.
"""
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from kezohar import config
from kezohar.llm import _post

QUESTIONS = ROOT / 'data/store/all-questions.json'
STORE = ROOT / 'data/store/question-taxonomy.json'
TITLES = {'prayer': 'תפילה ובית הכנסת', 'blessings': 'ברכות ואכילה', 'kashrut': 'כשרות והמטבח', 'shabbat': 'שבת בבית ובמשפחה',
          'women': 'הלכות נשים', 'holidays': 'חגים, ראש חודש וצומות', 'family': 'משפחה ומעגל החיים', 'health': 'בריאות ונגישות',
          'ethics': 'בין אדם לחברו ודיגיטל', 'money': 'כסף, עבודה ועסקים', 'daily': 'מצוות ושגרת היום', 'travel': 'נסיעות ואירוח',
          'tech': 'חשמל וטכנולוגיה', 'torah': 'תנ״ך, תורה ומחשבה'}
KINDS = ['מה אומרים', 'מותר או אסור', 'שכחתי · טעיתי', 'מתי', 'איך עושים', 'משמעות']
TORAH_KINDS = ['מי היה', 'מה קרה', 'מה זה', 'משמעות', 'איפה ומתי', 'מה נאמר']


def call(system, user, schema, name, tokens, timeout=180):
    body = {'model': config.llm_model(), 'temperature': 0, 'max_tokens': tokens, 'stream': False, '_prefer_strong': True,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': name, 'strict': True, 'schema': schema}},
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    return json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=timeout)['choices'][0]['message']['content'])


def span(n):
    return (3, 5) if n < 100 else (5, 8) if n < 700 else (8, 12) if n < 2500 else (12, 16)


def propose(cat, rows):
    lo, hi = span(len(rows))
    random.seed(3)
    sample = random.sample(rows, min(400, len(rows)))
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['topics'], 'properties': {'topics': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['name', 'definition'],
        'properties': {'name': {'type': 'string'}, 'definition': {'type': 'string'}}}}}}
    return call(f'אתה מארגן מאגר שאלות ותשובות ביהדות לאפליקציה בטלפון. הקטגוריה: "{TITLES.get(cat, cat)}". לפניך מדגם שאלות. '
                f'הצע {lo} עד {hi} נושאים, כך שלכל שאלה בקטגוריה יהיה בית אחד ברור, והנושאים יהיו בגודל דומה ככל האפשר. '
                'שם: 2–4 מילים בעברית פשוטה, כפי שאדם מחפש. אסור נושא כללי או סל ("מושגים", "שונות", "כללי", "נוספות"). '
                '"שכחתי/טעיתי" ו"מותר/אסור" אינם נושאים — אלה סוגי שאלות. הגדרה: משפט אחד — מה נכלל ומה לא. JSON בלבד.',
                '\n'.join('- ' + r['question'] for r in sample), schema, 'topics', 2500)['topics']


def assign(rows, topics, kinds, workers=6):
    """{question: [topic index, kind index]} for the rows."""
    names = [t['name'] for t in topics]
    guide = '\n'.join(f'- {t["name"]}: {t["definition"]}' for t in topics)
    item = {'type': 'object', 'additionalProperties': False, 'required': ['i', 'first_words', 'topic', 'kind'],
            'properties': {'i': {'type': 'integer'}, 'first_words': {'type': 'string'},
                           'topic': {'type': 'string', 'enum': names}, 'kind': {'type': 'string', 'enum': kinds}}}
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': item}}}
    system = ('לכל שאלה: המספר שלה, שתי המילים הראשונות שלה כפי שהן, הנושא שהיא שייכת אליו (אחד מהרשימה בלבד) וסוג השאלה. '
              'נושאים:\n' + guide + '\nJSON בלבד.')
    first = lambda q: q.split()[:2]
    out = {}

    def batch(chunk):
        try:
            got = call(system, '\n'.join(f'{i}. {r["question"]}' for i, r in enumerate(chunk)), schema, 'classify', 3500)['items']
        except Exception:
            return []
        return [(chunk[g['i']]['question'], names.index(g['topic']), kinds.index(g['kind'])) for g in got
                if 0 <= g['i'] < len(chunk) and first(chunk[g['i']]['question']) == first(g['first_words'])]

    todo = rows
    for _ in range(3):
        if not todo:
            break
        with ThreadPoolExecutor(workers) as pool:
            for part in pool.map(batch, [todo[i:i + 20] for i in range(0, len(todo), 20)]):
                for q, t, k in part:
                    out[q] = [t, k]
        todo = [r for r in todo if r['question'] not in out]
    one = {'type': 'object', 'additionalProperties': False, 'required': ['topic', 'kind'],
           'properties': {'topic': {'type': 'string', 'enum': names}, 'kind': {'type': 'string', 'enum': kinds}}}
    for r in todo:  # quotation marks at the start defeat the echo: these are asked alone
        try:
            g = call('הנושא של השאלה (מהרשימה) וסוגה. נושאים:\n' + guide, r['question'], one, 'one', 100, timeout=60)
            out[r['question']] = [names.index(g['topic']), kinds.index(g['kind'])]
        except Exception:
            pass
    return out


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def save(data):
    STORE.write_text(json.dumps(data, ensure_ascii=False))


def by_category():
    cats = {}
    for r in json.loads(QUESTIONS.read_text()):
        if r['category'] in TITLES:
            cats.setdefault(r['category'], []).append(r)
    return cats


def build(only=None):
    data, cats = load(), by_category()
    for cat, rows in cats.items():
        if only and cat not in only:
            continue
        kinds = TORAH_KINDS if cat == 'torah' else KINDS
        topics = propose(cat, rows)
        of = assign(rows, topics, kinds)
        data[cat] = {'topics': topics, 'kinds': kinds, 'of': of}
        save(data)
        print(cat, len(rows), 'questions →', len(topics), 'subjects;', len(rows) - len(of), 'unassigned', flush=True)


def update():
    data, cats = load(), by_category()
    for cat, rows in cats.items():
        if cat not in data:
            continue
        new = [r for r in rows if r['question'] not in data[cat]['of']]
        if new:
            data[cat]['of'].update(assign(new, data[cat]['topics'], data[cat]['kinds']))
            print(cat, len(new), 'new questions assigned', flush=True)
    save(data)


def export(out):
    data = load()
    app = {cat: {'topics': [t['name'] for t in d['topics']], 'kinds': d['kinds'], 'of': d['of']} for cat, d in data.items()}
    Path(out).write_text(json.dumps(app, ensure_ascii=False, separators=(',', ':')))
    print('exported', sum(len(d['of']) for d in app.values()), 'questions in', len(app), 'categories')


# Subjects the model made twice (reviewed by hand, 2026-10-20): merged into one, every question kept.
MERGES = {
    'holidays': [(['פורים ומגילה', 'מצוות פורים'], 'פורים'), (['ראש חודש', 'תפילות ראש חודש'], 'ראש חודש')],
    'kashrut': [(['בשר וחלב', 'בשר וחלב במטבח'], 'בשר וחלב')],
    'tech': [(['מכשירי חשמל אחרים', 'מקרר ומכשירי מטבח'], 'מכשירי חשמל ומטבח')],
    'travel': [(['תפילות וברכות בדרך', 'אירוח וסעודות'], 'אירוח, תפילה וברכות')],
}


def merge():
    data = load()
    for cat, rules in MERGES.items():
        d = data.get(cat)
        if not d:
            continue
        for names, into in rules:
            idx = [i for i, t in enumerate(d['topics']) if t['name'] in names]
            if len(idx) < 2:
                continue
            keep = idx[0]
            d['topics'][keep] = {'name': into, 'definition': ' '.join(d['topics'][i]['definition'] for i in idx)}
            for q, (t, k) in d['of'].items():
                if t in idx:
                    d['of'][q] = [keep, k]
        # drop emptied subjects and renumber
        used = sorted({t for t, _ in d['of'].values()})
        new = {old: n for n, old in enumerate(used)}
        d['topics'] = [d['topics'][i] for i in used]
        d['of'] = {q: [new[t], k] for q, (t, k) in d['of'].items()}
    save(data)
    print('merged')


if __name__ == '__main__':
    if sys.argv[1] == 'merge':
        merge()
    stage = sys.argv[1]
    if stage == 'build':
        build(sys.argv[2:] or None)
    elif stage == 'update':
        update()
    elif stage == 'export':
        export(sys.argv[2])
