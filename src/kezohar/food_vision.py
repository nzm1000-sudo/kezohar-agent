"""What is on the plate: a photo → the foods' names in Hebrew (owner, 2026-10-18: "the camera and the food").

The model only names what it sees; the blessing is decided by the app's own blessings engine, with its sources. A mixed
dish is named with its parts and which is the main one (עיקר), so the app can ask rather than assume. The photo is never
stored or logged. Gemini first (the free tier), then OpenAI.
"""
import base64
import json
import urllib.request

from . import config

SCHEMA = {'type': 'object', 'properties': {
    'items': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'name': {'type': 'string'}, 'kind': {'type': 'string'}, 'main': {'type': 'boolean'}, 'confidence': {'type': 'number'},
        'alternatives': {'type': 'array', 'items': {'type': 'string'}}},
        'required': ['name', 'kind', 'main', 'confidence', 'alternatives'], 'additionalProperties': False}},
    'not_food': {'type': 'boolean'},
    # A packaged product: the package's own words, read — never guessed (owner, 2026-10-18: a Tamar date bar filled with
    # almond butter was named "date and coconut bar").
    'product': {'type': 'object', 'properties': {'packaged': {'type': 'boolean'}, 'name': {'type': 'string'},
                                                 'brand': {'type': 'string'}, 'ingredients': {'type': 'string'},
                                                 'barcode': {'type': 'string'}},
                'required': ['packaged', 'name', 'brand', 'ingredients', 'barcode'], 'additionalProperties': False}},
    'required': ['items', 'not_food', 'product'], 'additionalProperties': False}

PROMPT = ('זהה את המאכלים והמשקאות שבתמונה, לצורך בירור ברכה. לכל אחד: name — שם המאכל בעברית פשוטה כפי שמחפשים אותו '
          '(למשל "שניצל", "אורז", "תפוח", "פיתה", "קולה", "עוגת שוקולד"); kind — סוג המאכל הכללי, משם שברשימה '
          '(למשל לדוריטוס "חטיף תירס", לאוראו "עוגיות", למילקי "מעדן חלב"); main — true למאכל העיקרי בצלחת, false לטפל; '
          'confidence — 0 עד 1. מנה מוכרת — קודם שם המנה כפי שאנשים קוראים לה, כפריט הראשי (שווארמה בפיתה, סביח, '
          'שישליק, פלאפל במנה, שקשוקה, קוגל, ג\'חנון, מלאווח), ורק אחריה רכיבים עיקריים כפריטים טפלים; אל תפרק מנה מוכרת '
          'לרכיבים בלבד. '
          'alternatives — עד שני שמות אחרים שהמאכל עשוי להיות, כשאינך בטוח (אחרת ריק). '
          'מאכלים שקל להחליף — הבחן היטב: חלבה (פירורית, בהירה, בגוש) ≠ קוסקוס; תמרים (חומים, מבריקים, מוארכים) ≠ תפוח '
          'אדמה; כרובית מטוגנת ≠ שניצל; פתיתים (כדוריות או גרגרים קטנים של בצק קלוי, "אורז" של פתיתים) ≠ פסטה (צורות '
          'גדולות: קרניים, פנה, ספגטי) ≠ קוסקוס (גרגרים זעירים) ≠ אורז; מלפפון (קליפה כהה עם בליטות) ≠ קישוא; בורקס ≠ '
          'מאפה שמרים; לביבה ≠ שניצל; חומוס (ממרח) ≠ טחינה; בורגול ≠ קינואה. '
          'אל תנחש מה שלא נראה. not_food=true אם אין בתמונה מאכל או משקה. עד 6 פריטים. '
          'מוצר ארוז: product.packaged=true, ו־name, brand ו־ingredients כפי שהם כתובים על האריזה, מילה במילה (כולל '
          'תיאור כמו "במילוי חמאת שקדים מצופה שוקולד מריר"); אל תוסיף רכיב שאינו כתוב או נראה. מה שלא נראה — מחרוזת ריקה. '
          'barcode — הספרות שמתחת לברקוד, אם נראות בבירור (8 או 13 ספרות), אחרת ריק. '
          'items למוצר ארוז: שם המוצר כפי שכתוב, ואחריו רכיביו העיקריים. אחרת packaged=false והשאר ריקים. JSON בלבד.')

MAX_BYTES = 1_500_000
# The blessings engine's own names (data/store/food-vocab.json, 2,809 after duplicates: the Oneg Shabbat table and the
# open food data), so a food is named as the engine knows it (owner, 2026-10-18: "the camera needs much knowledge").
_VOCAB = None


def vocab():
    global _VOCAB
    if _VOCAB is None:
        from pathlib import Path
        path = Path(config.get('FOOD_VOCAB', 'data/store/food-vocab.json'))
        _VOCAB = json.loads(path.read_text()) if path.exists() else []
    return _VOCAB


def pending_corrections():
    """Readers' corrections ("זוהה X — נכון Y", data/store/answer-ratings.jsonl), counted, newest pairs included."""
    from collections import Counter
    from pathlib import Path
    path = Path(config.get('ANSWER_RATINGS', 'data/store/answer-ratings.jsonl'))
    pairs = Counter()
    for line in (path.read_text().splitlines() if path.exists() else []):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get('kind') in ('food-camera-choice', 'food-camera-typed') and row.get('question', '').startswith('זוהה: '):
            pairs[(row['question'][6:].strip(), row.get('answer', '')[5:].strip())] += 1
    return pairs


def learned_corrections():
    """Only corrections the owner approved (data/store/food-corrections.json, scripts/review_corrections.py) teach the
    camera — a reader's correction waits in a queue, so one about a product never becomes a rule for all that look alike
    (owner, 2026-10-18)."""
    from pathlib import Path
    path = Path(config.get('FOOD_CORRECTIONS', 'data/store/food-corrections.json'))
    try:
        return [tuple(pair) for pair in json.loads(path.read_text()).get('approved', [])][:60]
    except (OSError, ValueError):
        return []


def identify(image_b64, timeout=30):
    """{'items': [{name, main, confidence}], 'not_food': bool} or None when no model could look."""
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return None
    if not raw or len(raw) > MAX_BYTES or raw[:3] != b'\xff\xd8\xff':  # a JPEG, made small by the app
        return None
    url = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode()
    names = vocab()
    prompt = PROMPT + (('\nשמות המאכלים במאגר הברכות — כשהמאכל שבתמונה מופיע ברשימה, השתמש בשם שבה בדיוק; מאכל שאינו ברשימה '
                        '(למשל מג׳דרה) — פרק לרכיביו שברשימה (אורז, עדשים):\n' + ' · '.join(names)) if names else '')
    learned = learned_corrections()
    if learned:
        prompt += '\nתיקונים שמשתמשים עשו בעבר (זוהה ← היה בפועל) — הבחן ביניהם היטב: ' + ' · '.join(f'{a} ← {b}' for a, b in learned)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {'url': url}}]}]
    fmt = {'type': 'json_schema', 'json_schema': {'name': 'foods', 'strict': True, 'schema': SCHEMA}}
    attempts = []
    if config.get('GEMINI_API_KEY', ''):
        for model in [config.get('GEMINI_VISION_MODEL', 'gemini-3.5-flash-lite'), 'gemini-3.8-flash']:
            attempts.append(('https://generativelanguage.googleapis.com/v1beta/openai/chat/completions', config.get('GEMINI_API_KEY'),
                             {'model': model, 'messages': messages, 'response_format': fmt, 'temperature': 0, 'reasoning_effort': 'low'}))
    if config.get('OPENAI_API_KEY', ''):
        attempts.append(('https://api.openai.com/v1/chat/completions', config.get('OPENAI_API_KEY'),
                         {'model': config.get('OPENAI_MODEL', 'gpt-6-luna'), 'messages': messages, 'response_format': fmt,
                          'reasoning_effort': 'none', 'max_completion_tokens': 400}))
    first = _ask(attempts)
    if first is None:
        return None
    main = next((item for item in first['items'] if item['main']), first['items'][0] if first['items'] else None)
    # Not sure: a stronger model looks too; agreement stands, disagreement becomes an alternative (research 2026-10-18).
    if main and main['confidence'] < 0.8 and config.get('GEMINI_API_KEY', ''):
        strong = [a for a in attempts if a[2].get('model') == 'gemini-3.8-flash'] + [a for a in attempts if 'openai.com' in a[0]]
        second = _ask(strong)
        if second and second['items']:
            other = next((item for item in second['items'] if item['main']), second['items'][0])
            if other['name'] != main['name'] and other['name'] not in main['alternatives']:
                if other['confidence'] > main['confidence']:
                    main['alternatives'] = [main['name']] + main['alternatives'][:1]
                    main.update(name=other['name'], kind=other['kind'], confidence=other['confidence'])
                else:
                    main['alternatives'] = ([other['name']] + main['alternatives'])[:2]
            if not first['product'] and second['product']:
                first['product'] = second['product']
    # A barcode read on the package: the product's own name from Open Food Facts (ODbL), when it has one.
    if first['product'] and first['product'].get('barcode'):
        found = barcode_product(first['product']['barcode'])
        if found:
            first['product'].update({k: v for k, v in found.items() if v})
            if first['items'] and found.get('name'):
                first['items'][0]['alternatives'] = ([first['items'][0]['name']] + first['items'][0]['alternatives'])[:2]
                first['items'][0]['name'] = found['name'][:60]
    return first


def barcode_product(code):
    """{'name', 'brand', 'ingredients'} from Open Food Facts for an EAN/UPC barcode, or None."""
    code = ''.join(ch for ch in str(code) if ch.isdigit())
    if len(code) not in (8, 12, 13, 14):
        return None
    url = f'https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=product_name_he,product_name,brands,ingredients_text_he,ingredients_text'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'KezoharAgent/1.0 (blessings camera)'}), timeout=6) as r:
            got = json.load(r)
    except Exception:
        return None
    p = got.get('product') or {}
    if got.get('status') != 1 or not (p.get('product_name_he') or p.get('product_name')):
        return None
    return {'name': p.get('product_name_he') or p.get('product_name'), 'brand': (p.get('brands') or '').split(',')[0].strip(),
            'ingredients': (p.get('ingredients_text_he') or p.get('ingredients_text') or '')[:300], 'barcode': code, 'from': 'openfoodfacts'}


def _ask(attempts, timeout=30):
    for endpoint, key, body in attempts:
        req = urllib.request.Request(endpoint, json.dumps(body).encode(),
                                     {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                got = json.loads(json.load(r)['choices'][0]['message']['content'])
        except Exception:
            continue  # a busy or limited model: the next one
        items = [{'name': ' '.join(str(i.get('name', '')).split())[:60], 'kind': ' '.join(str(i.get('kind', '')).split())[:40], 'main': bool(i.get('main')),
                  'alternatives': [' '.join(str(a).split())[:60] for a in (i.get('alternatives') or [])[:2] if str(a).strip()],
                  'confidence': max(0.0, min(1.0, float(i.get('confidence') or 0)))}
                 for i in (got.get('items') or [])[:6] if str(i.get('name', '')).strip()]
        product = got.get('product') or {}
        product = {k: ' '.join(str(product.get(k, '')).split())[:200] for k in ('name', 'brand', 'ingredients', 'barcode')} | {'packaged': bool(product.get('packaged'))}
        return {'items': items, 'not_food': bool(got.get('not_food')) and not items, 'product': product if product['packaged'] else None}
    return None
