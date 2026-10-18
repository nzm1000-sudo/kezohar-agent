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
                                                 'brand': {'type': 'string'}, 'ingredients': {'type': 'string'}},
                'required': ['packaged', 'name', 'brand', 'ingredients'], 'additionalProperties': False}},
    'required': ['items', 'not_food', 'product'], 'additionalProperties': False}

PROMPT = ('זהה את המאכלים והמשקאות שבתמונה, לצורך בירור ברכה. לכל אחד: name — שם המאכל בעברית פשוטה כפי שמחפשים אותו '
          '(למשל "שניצל", "אורז", "תפוח", "פיתה", "קולה", "עוגת שוקולד"); kind — סוג המאכל הכללי, משם שברשימה '
          '(למשל לדוריטוס "חטיף תירס", לאוראו "עוגיות", למילקי "מעדן חלב"); main — true למאכל העיקרי בצלחת, false לטפל; '
          'confidence — 0 עד 1. מאכל מורכב (סלט, פשטידה, מרק) — שמו, ואם רואים, גם רכיבים עיקריים כפריטים נפרדים. '
          'alternatives — עד שני שמות אחרים שהמאכל עשוי להיות, כשאינך בטוח (אחרת ריק). '
          'מאכלים שקל להחליף — הבחן היטב: פתיתים (כדוריות או גרגרים קטנים של בצק קלוי, "אורז" של פתיתים) ≠ פסטה (צורות '
          'גדולות: קרניים, פנה, ספגטי) ≠ קוסקוס (גרגרים זעירים) ≠ אורז; מלפפון (קליפה כהה עם בליטות) ≠ קישוא; בורקס ≠ '
          'מאפה שמרים; לביבה ≠ שניצל; חומוס (ממרח) ≠ טחינה; בורגול ≠ קינואה. '
          'אל תנחש מה שלא נראה. not_food=true אם אין בתמונה מאכל או משקה. עד 6 פריטים. '
          'מוצר ארוז: product.packaged=true, ו־name, brand ו־ingredients כפי שהם כתובים על האריזה, מילה במילה (כולל '
          'תיאור כמו "במילוי חמאת שקדים מצופה שוקולד מריר"); אל תוסיף רכיב שאינו כתוב או נראה. מה שלא נראה — מחרוזת ריקה. '
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
        product = {k: ' '.join(str(product.get(k, '')).split())[:200] for k in ('name', 'brand', 'ingredients')} | {'packaged': bool(product.get('packaged'))}
        return {'items': items, 'not_food': bool(got.get('not_food')) and not items, 'product': product if product['packaged'] else None}
    return None
