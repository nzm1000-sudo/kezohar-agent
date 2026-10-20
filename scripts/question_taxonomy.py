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


# Subjects with a natural order in time keep it (owner's rule, 2026-10-20); a category not listed here is shown א־ב.
# A subject not named in its list (a later rebuild) follows the listed ones, א־ב.
ORDERS = {
    'holidays': ['חמץ והכשרת הבית', 'פסח וסדר', 'ספירת העומר', 'שבועות', 'צומות החורבן', 'שופר ואלול', 'ראש השנה',
                 'יום הכיפורים', 'סוכות והסוכה', 'שמיני עצרת ושמחת תורה', 'חנוכה', 'פורים', 'ראש חודש'],
    'shabbat': ['הכנות לשבת', 'זמני שבת', 'נרות וקבלת שבת', 'קידוש ויין', 'סעודות שבת', 'מנהגי שולחן שבת', 'תפילה ולימוד שבת',
                'בישול וחימום', 'הכנת אוכל בשבת', 'מלאכות ומכשירים', 'מוקצה וטלטול', 'רשויות והוצאה', 'עירוב ותחומין',
                'ניקיון וטיפוח', 'דיבור וקריאה', 'הבדלה ומוצאי שבת'],
    'prayer': ['תפילין וציצית', 'זמני התפילה', 'תפילות היום', 'קריאת שמע וברכותיה', 'תפילת עמידה', 'קדיש ותחנון',
               'קריאת התורה', 'ספר תורה', 'ברכות ותפילות נוספות', 'מניין וחזן', 'בית הכנסת'],
    'blessings': ['ברכות על מאכלים', 'ברכות בסעודה', 'שיעורי אכילה ושתייה', 'ברכת המזון', 'זימון וסועדים', 'ברכות אחרונות',
                  'ברכות הודאה ושבח', 'ברכות הריח', 'ברכות ראייה', 'ברכת האילנות'],
    'family': ['דיבור עם הורים', 'כבוד לחותנים ולמשפחה', 'כיבוד הורים', 'סיוע וטיפול בהורים', 'ציות להורים', 'קשר וביקורים',
               'פטירה והלוויה', 'שבעה ושלושים', 'שנת אבל וקדיש', 'אזכרות ועלייה לקבר', 'מצוות ומנהגי משפחה'],
    'daily': ['כתיבת מזוזה', 'קביעת מזוזה', 'מזוזה בבית', 'בדיקת מזוזה', 'חובת ציצית', 'חוטי ציצית', 'לבישת טלית', 'בדיקת ציצית',
              'מנהגי חתונה וברית', 'מנהגי קהילה ולבוש', 'מנהגי שבת וחגים', 'תפילה ופיוט'],
    'torah': ['סיפורי בראשית', 'יציאת מצרים', 'נדודי המדבר', 'המשכן והכהונה', 'כיבוש הארץ', 'שופטים ומלכים', 'נביאים וכתובים',
              'תפילה ותהילים', 'משנה ותלמוד', 'גאונים וישיבות', 'פרשני התורה', 'הלכה וספרי פסיקה', 'מצוות ודיני תורה',
              'מועדים ומנהגים', 'קבלה וחסידות', 'הגות ואמונה'],
}


def export(out):
    data = load()
    app = {cat: {'topics': [t['name'] for t in d['topics']], 'kinds': d['kinds'], 'of': d['of'],
                 **({'order': [n for n in ORDERS[cat] if n in [t['name'] for t in d['topics']]]} if cat in ORDERS else {})}
           for cat, d in data.items()}
    for cat, names in ORDERS.items():
        missing = set(names) - {t['name'] for t in data.get(cat, {}).get('topics', [])}
        if missing:
            print('order names not in', cat, missing)
    Path(out).write_text(json.dumps(app, ensure_ascii=False, separators=(',', ':')))
    print('exported', sum(len(d['of']) for d in app.values()), 'questions in', len(app), 'categories')


def kinds(only=None):
    """Each category its own kinds (owner, 2026-10-20: "the same tags in every category is not right"): the model proposes
    5–6 from a sample, then every question gets one; the subjects stay."""
    data, cats = load(), by_category()
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['kinds'], 'properties': {'kinds': {'type': 'array', 'items': {'type': 'string'}}}}
    for cat, rows in cats.items():
        if cat not in data or (only and cat not in only):
            continue
        random.seed(5)
        sample = random.sample(rows, min(300, len(rows)))
        names = call(f'אתה מארגן מאגר שאלות ותשובות ביהדות בטלפון. הקטגוריה: "{TITLES.get(cat, cat)}". הצע 6 תגיות (בדיוק 6 אם '
                     'יש בקטגוריה מספיק גיוון, אחרת 4) שבהן אדם יסנן את שאלות הקטגוריה הזו — לפי מה שהוא מחפש או המצב שבו הוא '
                     'נמצא, לא לפי נושא (הנושאים כבר קיימים). כל תגית 1–3 מילים, חיה ומדוברת, מתאימה דווקא לקטגוריה הזו '
                     '(למשל בשבת: "מותר בשבת?", "מה מכינים מראש"; בתנ״ך: "מי היה", "איפה זה קרה"). ביחד הן מכסות כמעט כל שאלה. JSON בלבד.',
                     '\n'.join('- ' + r['question'] for r in sample), schema, 'kinds', 400)['kinds']
        names = [n.strip() for n in names if n.strip()][:6]
        d = data[cat]
        topics = d['topics']
        # the kind only: the subject is kept as it is
        item = {'type': 'object', 'additionalProperties': False, 'required': ['i', 'first_words', 'kind'],
                'properties': {'i': {'type': 'integer'}, 'first_words': {'type': 'string'}, 'kind': {'type': 'string', 'enum': names}}}
        sch = {'type': 'object', 'additionalProperties': False, 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': item}}}
        system = 'לכל שאלה: המספר שלה, שתי המילים הראשונות שלה כפי שהן, והתגית המתאימה לה ביותר מהרשימה: ' + ' / '.join(names) + '. JSON בלבד.'
        first = lambda q: q.split()[:2]
        got = {}

        def batch(chunk):
            try:
                res = call(system, '\n'.join(f'{i}. {r["question"]}' for i, r in enumerate(chunk)), sch, 'kind', 2500)['items']
            except Exception:
                return []
            return [(chunk[g['i']]['question'], names.index(g['kind'])) for g in res
                    if 0 <= g['i'] < len(chunk) and first(chunk[g['i']]['question']) == first(g['first_words'])]
        todo = [r for r in rows if r['question'] in d['of']]
        for _ in range(3):
            if not todo:
                break
            with ThreadPoolExecutor(6) as pool:
                for part in pool.map(batch, [todo[i:i + 20] for i in range(0, len(todo), 20)]):
                    for q, k in part:
                        got[q] = k
            todo = [r for r in todo if r['question'] not in got]
        for q, k in got.items():
            d['of'][q] = [d['of'][q][0], k]
        d['kinds'] = names
        save(data)
        print(cat, names, len(got), 'of', len(rows), flush=True)


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
    elif sys.argv[1] == 'kinds':
        kinds(sys.argv[2:] or None)
    stage = sys.argv[1]
    if stage == 'build':
        build(sys.argv[2:] or None)
    elif stage == 'update':
        update()
    elif stage == 'export':
        export(sys.argv[2])
