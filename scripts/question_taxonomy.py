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
    return (3, 5) if n < 100 else (5, 8) if n < 700 else (8, 12) if n < 2500 else (12, 16) if n < 4500 else (16, 22)


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
    'holidays': ['חמץ ובדיקתו', 'הכשרת לפסח', 'ערב פסח', 'פסח והסדר', 'חול המועד', 'יום טוב', 'ספירת העומר', 'מנהגי העומר',
                 'שבועות', 'ארבע תעניות', 'סליחות ותשובה', 'ראש השנה', 'יום כיפור', 'סוכות וסוכה', 'ארבעת המינים',
                 'שמיני עצרת ושמחת תורה', 'חנוכה', 'ט״ו בשבט', 'תענית אסתר', 'פורים', 'קידוש החודש', 'ראש חודש'],
    'shabbat': ['הכנות לכבוד שבת', 'כניסת ויציאת שבת', 'הדלקת נרות שבת', 'קידוש על היין', 'סעודות שבת ולחם', 'זמירות ושיחות שבת',
                'תפילות שבת וקריאה', 'חימום והחזרת אוכל', 'בישול בשבת', 'הכנת אוכל בשבת', 'ברירה וסחיטה בשבת', 'תה ומשקאות בשבת',
                'ניקיון וכביסה בשבת', 'תיקון ופתיחת חפצים', 'חשמל ומכשירים בבית', 'מוקצה וטלטול חפצים', 'עירוב והוצאה בשבת',
                'לבוש, משחק ויציאה', 'דיבור, מסחר ועבודה', 'אמירה לגוי והנאה ממלאכה', 'חולה, רפואה ופיקוח נפש', 'הבדלה במוצאי שבת'],
    'prayer': ['נטילת ידיים', 'ברכות השחר', 'ציצית וטלית', 'תפילין', 'זמני התפילה', 'סדר התפילה', 'נוסח התפילה', 'קריאת שמע',
               'תפילת העמידה', 'כוונה ותנועות', 'הפסק בתפילה', 'תוספות לתפילה', 'תחנון וימים מיוחדים', 'נשיאת כפיים',
               'קדיש וקדושה', 'תפילה בציבור', 'שליח ציבור', 'קריאת התורה', 'ספרי תורה ותשמישי קדושה', 'בית הכנסת',
               'תפילות שבת וחג', 'ברכות ותפילות נוספות'],
    'blessings': ['נטילת ידיים', 'ברכות על לחם', 'ברכות על מאכלים', 'מאכלים מעורבים', 'קדימה ופטור בברכות', 'ברכות הנהנין בספק',
                  'ברכות בתוך הסעודה', 'שיעורי אכילה ושתייה', 'ברכת המזון', 'זימון', 'ברכה אחרונה', 'ברכות על ריח',
                  'ברכות על ראייה', 'ברכת שהחיינו', 'ברכות הודאה ותפילה'],
    'family': ['ברית מילה', 'חינוך ילדים', 'בר ובת מצווה', 'שידוכים ונישואין', 'בית ומנהגי משפחה', 'כיבוד הורים', 'ציות להורים',
               'עזרה להורים', 'חולה ורפואה', 'גירושין וגט', 'אנינות וקבורה', 'קריעה והספדים', 'שבעה ואבלות', 'דיני אבלים',
               'קדיש ואזכרה'],
    'torah': ['סיפורי בראשית', 'יציאת מצרים', 'נדודי המדבר', 'המשכן והכהונה', 'כיבוש הארץ', 'שופטים ומלכים', 'נביאים וכתובים',
              'תפילה ותהילים', 'משנה ותלמוד', 'גאונים וישיבות', 'פרשני התורה', 'הלכה וספרי פסיקה', 'מצוות ודיני תורה',
              'מועדים ומנהגים', 'קבלה וחסידות', 'הגות ואמונה'],
}


def short(question):
    """The app's own short id of a question (ravBariBank.mjs › bankId, without "rb-"): the catalog keyed by it, not by
    the question's words (2026-10-20: the words made the file 2.3 MB)."""
    h = 5381
    for ch in question:
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    digits, out = '0123456789abcdefghijklmnopqrstuvwxyz', ''
    while True:
        h, r = divmod(h, 36)
        out = digits[r] + out
        if not h:
            return out


def export(out):
    data = load()
    app = {cat: {'topics': [t['name'] for t in d['topics']], 'kinds': d['kinds'], 'of': {short(q): v for q, v in d['of'].items()},
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


# A question shown in a second category too (owner, 2026-10-21: "health and women's laws so few — makes no sense"): the
# bank files a question by its book (a sick person on Shabbat is in Shabbat); these categories gather them from everywhere.
# Words find the candidates; the model keeps only what truly belongs. data/store/cross-list.json {question: [category]}.
CROSS = {
    'health': ('בריאות, חולים ורפואה (חולה, תרופה, רופא, בית חולים, יולדת, פיקוח נפש, נגישות ומוגבלות)',
               r'חולה|חולים|רפוא|תרופ|רופא|יולדת|בית חולים|ניתוח|כאב|נכה|כסא גלגלים|שמיעה|פיקוח נפש|קשיש|חירש|עיוור|מכשיר|אלרגי|סכרת|הריון|מעוברת'),
    'women': ('הלכות שנוגעות לנשים במיוחד (חיובי נשים במצוות, הדלקת נרות, הפרשת חלה, צניעות, כלה, יולדת, אישה כשליחה)',
              r'אישה|אשה|נשים|האשה|בנות|כלה|יולדת|הפרשת חלה|הדלקת נרות|צניעות|כיסוי ראש|פאה|בעלה|נערה|מעוברת|מניקה'),
    'tech': ('חשמל, מכשירים וטכנולוגיה (חשמל בשבת ובחג, מעלית, טלפון, מחשב, מזגן, שעון שבת, מצלמות וחיישנים)',
             r'חשמל|טלפון|מעלית|מחשב|אינטרנט|שעון שבת|מזגן|מקרר|מצלמ|חיישן|אפליקצי|וואטסאפ|רשת|מכשיר|נורה|מנורה|תאורה|פלטה'),
    'travel': ('נסיעות, טיסות ואירוח (בדרך, במטוס, במלון, בחוץ לארץ, אצל מארחים, תפילת הדרך)',
               r'נסיע|טיסה|מטוס|מלון|חו"ל|חו״ל|חוץ לארץ|תפילת הדרך|רכב|אוטובוס|רכבת|אכסני|מתארח|אורח|בדרך'),
}


def cross():
    import re as _re
    path = ROOT / 'data/store/cross-list.json'
    out = json.loads(path.read_text()) if path.exists() else {}
    # Every (question, category) already judged — kept or not — is not asked again on the next run.
    seen_path = ROOT / 'data/store/cross-seen.json'
    seen = set(map(tuple, json.loads(seen_path.read_text()))) if seen_path.exists() else {(q, c) for q, cats in out.items() for c in cats}
    rows = [r for r in json.loads(QUESTIONS.read_text())]
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['i', 'first_words', 'belongs'],
        'properties': {'i': {'type': 'integer'}, 'first_words': {'type': 'string'}, 'belongs': {'type': 'boolean'}}}}}}
    first = lambda q: q.split()[:2]
    for cat, (title, pattern) in CROSS.items():
        cands = [r for r in rows if r['category'] != cat and _re.search(pattern, r['question']) and (r['question'], cat) not in seen]
        system = (f'לכל שאלה: המספר שלה, שתי המילים הראשונות שלה כפי שהן, והאם היא שייכת גם לקטגוריה "{title}" — '
                  'כלומר אדם שמחפש בקטגוריה הזו היה מצפה למצוא אותה שם. מילה משותפת בלבד אינה מספיקה. JSON בלבד.')

        def batch(chunk):
            try:
                got = call(system, '\n'.join(f'{i}. {r["question"]}' for i, r in enumerate(chunk)), schema, 'cross', 2000)['items']
            except Exception:
                return []
            return [chunk[g['i']]['question'] for g in got if g['belongs'] and 0 <= g['i'] < len(chunk)
                    and first(chunk[g['i']]['question']) == first(g['first_words'])]
        kept = 0
        with ThreadPoolExecutor(6) as pool:
            for part in pool.map(batch, [cands[i:i + 20] for i in range(0, len(cands), 20)]):
                for q in part:
                    out.setdefault(q, []).append(cat)
                    kept += 1
        seen |= {(r['question'], cat) for r in cands}
        path.write_text(json.dumps(out, ensure_ascii=False))
        seen_path.write_text(json.dumps(sorted(seen), ensure_ascii=False))
        print(cat, len(cands), 'candidates →', kept, 'kept', flush=True)


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
    elif sys.argv[1] == 'cross':
        cross()
    elif sys.argv[1] == 'kinds':
        kinds(sys.argv[2:] or None)
    stage = sys.argv[1]
    if stage == 'build':
        build(sys.argv[2:] or None)
    elif stage == 'update':
        update()
    elif stage == 'export':
        export(sys.argv[2])
