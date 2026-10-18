"""The food-camera's image bank (owner, 2026-10-18: "a bank of photos that teach the agent, not in the app").

Photos of everyday foods from Wikimedia Commons (free licences), kept on this computer only (data/store/food-eval,
git-ignored), each run through food_vision.identify; a food counts as recognised when one of its expected names (or a
word of them) is among the names returned. Writes results.jsonl and prints the accuracy and the misses, so the prompt
can be tuned against real photos rather than guesses. Resumable.

Usage: food_eval.py [download|run|report]
"""
import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
OUT = ROOT / 'data/store/food-eval'
UA = {'User-Agent': 'KezoharAgent/1.0 (food blessing evaluation; owner nitz)'}

# (Commons search, the names a correct answer may use)
FOODS = [
    ('pita bread', ['פיתה', 'לחם']), ('challah bread', ['חלה', 'לחם']), ('bagel', ['בייגל', 'בגל', 'לחם']),
    ('sliced bread loaf', ['לחם']), ('matzah', ['מצה']), ('croissant', ['קרואסון']), ('burekas', ['בורקס']),
    ('rugelach', ['רוגלך']), ('chocolate cake slice', ['עוגה', 'עוגת שוקולד']), ('cheesecake', ['עוגת גבינה', 'עוגה']),
    ('cookies plate', ['עוגיות', 'עוגייה']), ('pretzels', ['בייגלה', 'פרצל']), ('crackers', ['קרקר']),
    ('pasta spaghetti plate', ['ספגטי', 'פסטה']), ('couscous', ['קוסקוס']), ('rice bowl', ['אורז']),
    ('oatmeal porridge', ['שיבולת שועל', 'דייסה']), ('cornflakes bowl', ['קורנפלקס', 'דגני בוקר']),
    ('pizza slice', ['פיצה']), ('falafel pita', ['פלאפל']), ('shawarma', ['שווארמה']), ('hummus plate', ['חומוס']),
    ('shakshuka', ['שקשוקה']), ('schnitzel', ['שניצל']), ('roast chicken', ['עוף']), ('grilled steak', ['סטייק', 'בשר']),
    ('gefilte fish', ['גפילטע', 'דג']), ('salmon fillet', ['סלמון', 'דג']), ('sushi', ['סושי']), ('omelette', ['חביתה']),
    ('boiled eggs', ['ביצה', 'ביצים']), ('cholent', ["צ'ולנט", 'חמין']), ('chicken soup', ['מרק']),
    ('israeli salad', ['סלט']), ('french fries', ['צ\'יפס', 'טוגנים']), ('potato kugel', ['קוגל']),
    ('latkes potato pancakes', ['לביבות', 'לביבה']), ('sufganiyah', ['סופגנייה', 'סופגניה']),
    ('apple fruit', ['תפוח']), ('banana', ['בננה']), ('orange fruit', ['תפוז']), ('grapes', ['ענבים']),
    ('watermelon slice', ['אבטיח']), ('strawberries', ['תות']), ('dates fruit', ['תמר', 'תמרים']), ('figs', ['תאנה', 'תאנים']),
    ('pomegranate', ['רימון']), ('olives', ['זיתים', 'זית']), ('mango', ['מנגו']), ('pineapple', ['אננס']),
    ('cherry tomatoes', ['עגבנייה', 'עגבניה', 'שרי']), ('cucumber', ['מלפפון']), ('carrots', ['גזר']), ('corn on the cob', ['תירס']),
    ('avocado', ['אבוקדו']), ('peanuts', ['בוטנים', 'בוטן']), ('almonds', ['שקדים', 'שקד']), ('walnuts', ['אגוזים', 'אגוז']),
    ('popcorn', ['פופקורן']), ('potato chips', ['צ\'יפס', 'חטיף']), ('bamba snack', ['במבה']), ('chocolate bar', ['שוקולד']),
    ('ice cream', ['גלידה']), ('yogurt', ['יוגורט']), ('cheese platter', ['גבינה', 'גבינות']), ('honey', ['דבש']),
    ('glass of wine', ['יין']), ('glass of water', ['מים']), ('coffee cup', ['קפה']), ('tea cup', ['תה']),
    ('orange juice', ['מיץ']), ('cola soda', ['קולה', 'משקה']), ('beer glass', ['בירה']), ('milk glass', ['חלב']),
    ('lentil soup', ['מרק', 'עדשים']), ('mujaddara', ['מג\'דרה', 'אורז', 'עדשים']), ('jachnun', ["ג'חנון"]), ('malawach', ['מלאווח']),
    # Israeli dishes and snacks (owner, 2026-10-18: "more photos")
    ('sabich', ['סביח']), ('bourekas', ['בורקס']), ('kubbeh', ['קובה']), ('ptitim', ['פתיתים']), ('israeli couscous', ['פתיתים', 'קוסקוס']),
    ('tahini', ['טחינה']), ('labneh', ['לאבנה']), ('halva', ['חלבה']), ('baklava', ['בקלאווה']), ('knafeh', ['כנאפה']),
    ('kugel', ['קוגל']), ('cholent', ["צ'ולנט", 'חמין']), ('hamantaschen', ['אוזני המן']), ('babka', ['בבקה', 'עוגת שמרים']),
    ('rugelach', ['רוגלך', 'רוגעלך']), ('challah', ['חלה', 'לחם']), ('matzo ball soup', ['מרק', 'קניידלך']), ('kreplach', ['קרעפלך']),
    ('shawarma laffa', ['שווארמה', 'לאפה']), ('laffa bread', ['לאפה', 'לחם']), ('schnitzel plate', ['שניצל']), ('kebab', ['קבב']),
    ('stuffed peppers', ['פלפל ממולא', 'ממולאים']), ('stuffed grape leaves', ['עלי גפן', 'ממולאים']), ('moussaka', ['מוסקה']),
    ('pastilla', ['פסטל']), ('cheese blintzes', ['בלינצס']), ('latke', ['לביבה', 'לביבות']), ('fried cauliflower', ['כרובית']),
    ('roasted eggplant', ['חציל']), ('matbucha', ['מטבוחה']), ('schug', ['סחוג']), ('amba', ['עמבה']), ('date honey silan', ['סילאן', 'דבש']),
    ('pomegranate seeds', ['רימון']), ('sunflower seeds', ['גרעינים']), ('pita chips', ['חטיף', 'פיתה']), ('wafer snack', ['ופל', 'ופלים']),
    ('rice cakes', ['פריכיות']), ('granola bar', ['חטיף דגנים', 'גרנולה']),
]


def search(term):
    q = urllib.parse.urlencode({'action': 'query', 'generator': 'search', 'gsrnamespace': 6, 'gsrsearch': f'{term} filetype:bitmap',
                                'gsrlimit': 5, 'prop': 'imageinfo', 'iiprop': 'url|extmetadata', 'iiurlwidth': 640, 'format': 'json'})
    with urllib.request.urlopen(urllib.request.Request('https://commons.wikimedia.org/w/api.php?' + q, headers=UA), timeout=20) as r:
        pages = json.load(r).get('query', {}).get('pages', {}).values()
    for page in sorted(pages, key=lambda p: p.get('index', 99)):
        info = (page.get('imageinfo') or [{}])[0]
        if info.get('thumburl', '').lower().split('?')[0].endswith(('.jpg', '.jpeg')):
            return info['thumburl'], page.get('title'), (info.get('extmetadata', {}).get('LicenseShortName', {}) or {}).get('value')
    return None


def openverse(term, n=3):
    """Up to n freely licensed photos (commercial use allowed) from Openverse — Flickr, Wikimedia and more, no key."""
    q = urllib.parse.urlencode({'q': term, 'page_size': n + 3, 'license_type': 'commercial', 'extension': 'jpg'})
    with urllib.request.urlopen(urllib.request.Request('https://api.openverse.org/v1/images/?' + q, headers=UA), timeout=20) as r:
        results = json.load(r).get('results', [])
    return [(x['url'], x.get('title') or '', f"{x.get('license')} · {x.get('source')} · {x.get('creator') or ''}") for x in results][:n]


def download_more(per=3):
    """More photos per food from Openverse (owner, 2026-10-18: "take what you can"), each kept with its licence."""
    meta = OUT / 'photos.jsonl'
    have = [json.loads(l) for l in meta.read_text().splitlines()] if meta.exists() else []
    count = {}
    for row in have:
        count[row['term']] = count.get(row['term'], 0) + 1
    with meta.open('a') as out:
        for term, names in FOODS:
            if count.get(term, 0) >= per + 1:
                continue
            try:
                found = openverse(term, per)
            except Exception as exc:
                print('openverse failed:', term, type(exc).__name__)
                time.sleep(10)
                continue
            for i, (url, title, licence) in enumerate(found):
                path = OUT / f"{term.replace(' ', '_')}_ov{i}.jpg"
                if path.exists():
                    continue
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                        data = r.read(4_000_000)
                except Exception:
                    continue
                if data[:3] != b'\xff\xd8\xff':
                    continue
                path.write_bytes(data)
                import subprocess  # as the phone does: the longest side 768 px
                subprocess.run(['sips', '-Z', '768', str(path)], capture_output=True)
                out.write(json.dumps({'term': term, 'names': names, 'file': path.name, 'title': title, 'licence': licence}, ensure_ascii=False) + '\n')
                out.flush()
            time.sleep(3)


def download():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = OUT / 'photos.jsonl'
    have = {json.loads(l)['term'] for l in meta.read_text().splitlines()} if meta.exists() else set()
    with meta.open('a') as out:
        for term, names in FOODS:
            if term in have:
                continue
            try:
                found = search(term)
                if not found:
                    print('no photo:', term)
                    continue
                url, title, licence = found
                path = OUT / (term.replace(' ', '_') + '.jpg')
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                    path.write_bytes(r.read())
                out.write(json.dumps({'term': term, 'names': names, 'file': path.name, 'title': title, 'licence': licence}, ensure_ascii=False) + '\n')
                out.flush()
                time.sleep(4)
            except Exception as exc:
                print('failed:', term, type(exc).__name__)


def run():
    from kezohar.food_vision import identify
    results = OUT / 'results.jsonl'
    done = {json.loads(l)['term'] for l in results.read_text().splitlines()} if results.exists() else set()
    with results.open('a') as out:
        for row in map(json.loads, (OUT / 'photos.jsonl').read_text().splitlines()):
            if row['term'] in done:
                continue
            got = identify(base64.b64encode((OUT / row['file']).read_bytes()).decode())
            names = [i['name'] for i in (got or {}).get('items', [])]
            hit = any(any(want in name or name in want for name in names) for want in row['names'])
            out.write(json.dumps({**row, 'got': names, 'hit': hit}, ensure_ascii=False) + '\n')
            out.flush()


def report():
    rows = [json.loads(l) for l in (OUT / 'results.jsonl').read_text().splitlines()]
    hits = sum(r['hit'] for r in rows)
    print(f'recognised {hits}/{len(rows)} ({round(100 * hits / max(1, len(rows)))}%)')
    for r in rows:
        if not r['hit']:
            print(' miss:', r['term'], '→', r['got'], '(expected', r['names'][0] + ')')


if __name__ == '__main__':
    {'download': download, 'more': download_more, 'run': run, 'report': report}[sys.argv[1] if len(sys.argv) > 1 else 'report']()
