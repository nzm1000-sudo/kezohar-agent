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
        'name': {'type': 'string'}, 'main': {'type': 'boolean'}, 'confidence': {'type': 'number'}},
        'required': ['name', 'main', 'confidence'], 'additionalProperties': False}},
    'not_food': {'type': 'boolean'}}, 'required': ['items', 'not_food'], 'additionalProperties': False}

PROMPT = ('זהה את המאכלים והמשקאות שבתמונה, לצורך בירור ברכה. לכל אחד: name — שם המאכל בעברית פשוטה כפי שמחפשים אותו '
          '(למשל "שניצל", "אורז", "תפוח", "פיתה", "קולה", "עוגת שוקולד"); main — true למאכל העיקרי בצלחת, false לטפל; '
          'confidence — 0 עד 1. מאכל מורכב (סלט, פשטידה, מרק) — שמו, ואם רואים, גם רכיבים עיקריים כפריטים נפרדים. '
          'אל תנחש מה שלא נראה. not_food=true אם אין בתמונה מאכל או משקה. עד 6 פריטים. JSON בלבד.')

MAX_BYTES = 1_500_000


def identify(image_b64, timeout=30):
    """{'items': [{name, main, confidence}], 'not_food': bool} or None when no model could look."""
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return None
    if not raw or len(raw) > MAX_BYTES or raw[:3] != b'\xff\xd8\xff':  # a JPEG, made small by the app
        return None
    url = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode()
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': PROMPT}, {'type': 'image_url', 'image_url': {'url': url}}]}]
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
        items = [{'name': ' '.join(str(i.get('name', '')).split())[:40], 'main': bool(i.get('main')),
                  'confidence': max(0.0, min(1.0, float(i.get('confidence') or 0)))}
                 for i in (got.get('items') or [])[:6] if str(i.get('name', '')).strip()]
        return {'items': items, 'not_food': bool(got.get('not_food')) and not items}
    return None
