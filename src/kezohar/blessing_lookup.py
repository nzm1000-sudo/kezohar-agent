"""'מה מברכים על…' from the app's verified blessings table, before any model memory (owner, 2026-10-18: a potato-dough
snack, Osem's דובונים, was answered "בורא פרי האדמה" from memory — it is שהכל).

data/store/food-blessings.json is the blessings engine's own table (scripts/food_blessings.mjs): names, the blessing
before and after, and the source. A food is matched by a whole name only — the asked words, or the asked words cut from
their end — never by a near spelling, so another food's blessing is never given. No match: the usual path answers.
"""
import json
import re
from pathlib import Path

from . import config

ASKED = re.compile(r'^\s*(?:ו?מה|איזו\s+ברכה|איזה\s+ברכה)\s+(?:מברכים|מברכין|מברך|ברכה|הברכה)\s+(?:על|ל|ב)\s*(.+?)\s*\??\s*$')
_TABLE = None
# A name cut down to one of these alone says nothing of which food it is (חטיף תמרים → חטיף → a candy's blessing).
GENERIC = {'חטיף', 'חטיפי', 'חטיפים', 'ממתק', 'ממתקים', 'עוגה', 'עוגת', 'עוגות', 'עוגיות', 'עוגייה', 'משקה', 'משקאות', 'מאכל',
           'סלט', 'מרק', 'שוקולד', 'לחם', 'גבינה', 'גבינת', 'מיץ', 'רוטב', 'ממרח', 'קרם', 'פשטידה', 'מעדן', 'דגני', 'בטעם', 'מוצר'}
# A brand the book itself rules on (the app's data/blessings/verifiedCorrections.mjs, the same words): checked first.
BRANDS = [(re.compile(r'קורנפלקס.*(?:תלמה|אלופים)|(?:תלמה|אלופים).*קורנפלקס'),
           {'names': ['קורנפלקס של תלמה'], 'before': 'שהכל נהיה בדברו', 'after': 'בורא נפשות',
            'cite': 'עונג שבת, פרק כ״ו (לוח ברכות): "הקורנפלקס המיוצר כיום בחברת תלמה, עשוי מקמח תירס — ברכתו שהכל / נפשות"'})]


def _norm(text):
    text = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', str(text))
    text = re.sub(r'[׳\'"״`’]', '', text)
    text = re.sub(r'[^א-תA-Za-z0-9 ]', ' ', text)
    return ' '.join(text.lower().split())


def table():
    global _TABLE
    if _TABLE is None:
        path = Path(config.get('FOOD_BLESSINGS', 'data/store/food-blessings.json'))
        rows = json.loads(path.read_text()) if path.exists() else []
        _TABLE = {}
        for row in rows:
            for name in row['names']:
                _TABLE.setdefault(_norm(name), row)
    return _TABLE


def lookup(question):
    m = ASKED.match(question.split('\n')[0])
    if not m:
        return None
    # The food's name only: what the camera adds after it (", הרכיבים: …") names other foods.
    asked = re.split(r'\?|הרכיבים|רכיבים:', m.group(1))[0]
    brand = next((row for pattern, row in BRANDS if pattern.search(asked)), None)
    words = _norm(re.sub(r'^(?:ה|את\s+ה?)', '', asked)).split()
    rows = table()
    # The whole name, then shorter from its end ("דובונים חטיף תפוח אדמה בטעם טבעי" → "דובונים"), two letters at least.
    for size in range(len(words), 0, -1):
        key = ' '.join(words[:size])
        row = brand or rows.get(key) or rows.get('ה' + key if not key.startswith('ה') else key[1:])
        if size < len(words) and size == 1 and key in GENERIC:
            break
        if row and len(key) >= 2:
            name = row['names'][0].split('[')[0].strip()
            answer = f'על {name} מברכים «{row["before"]}», ולאחר האכילה «{row["after"]}».'
            cite = row.get('cite') or 'מנוע הברכות'
            return {'verdict': 'ok', 'mode': 'summary-with-quote', 'answer': answer + f'\n\nמקור: {cite}.',
                    'sources': [{'reference': cite}], 'halachic_verified': False,
                    'bari': {'answer': answer, 'quote': None, 'cite': cite, 'source': 'library'},
                    'blessing_lookup': {'matched': key}}
    return None


if __name__ == '__main__':
    for q in ['מה מברכים על דובונים חטיף תפוח אדמה בטעם טבעי?', 'מה מברכים על בננה?', 'מה מברכים על דובוני גומי?', 'מה מברכים על חטיף תמרים במילוי?']:
        r = lookup(q)
        print(q, '→', r and r['answer'])
