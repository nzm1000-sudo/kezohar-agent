"""Public gateway: the only door from the internet (via Cloudflare Tunnel) to the local agent.

Listens on 127.0.0.1:8720. Exposes POST /demo/ask and /demo/speak (an answer read aloud) only, requires the app key, limits size and rate per client,
allows three answers at a time with a short queue, forwards to the loopback agent (127.0.0.1:8711) and returns only
the answer fields the app shows. Each request's duration and question go to data/store/gateway-timing.log (owner, 2026-10-16).
"""
import asyncio
import json
import os
import secrets
import time
import urllib.request
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / 'data/store/public_gateway.key'
UPSTREAM = os.environ.get('KEZOHAR_AGENT_UPSTREAM', 'http://127.0.0.1:8711')
ORIGINS = {'https://nzm1000-sudo.github.io', 'capacitor://localhost', 'https://localhost', 'http://localhost'}
PER_MINUTE, PER_DAY, QUEUE = 6, 150, 3
# Of a device's questions, at most 70 a day are answered with the paid model (owner, 2026-10-23: "by Luna, not by halacha
# questions"); then the free paths still answer — the blessings table, the ready bank, answers already given, commentators.
LUNA_PER_DAY = int(os.environ.get('KEZOHAR_LUNA_PER_DAY', '70'))
FREE_MODES = {'fast', 'refuse', 'scope', 'clarification', 'limited'}
# An internet address may be shared by a whole home, yeshiva or phone company (owner, 2026-10-18), so the allowance is
# per device (the app's random install id); the address keeps only a wide ceiling, against one caller inventing devices.
ADDRESS_PER_MINUTE, ADDRESS_PER_DAY = 40, 2000
# The whole service's daily ceiling, whatever the address (security review 2026-10-18: the app key is public, so a caller
# changing addresses could run up the paid models' bill): questions, readings aloud and word timings.
GLOBAL_PER_DAY = {'ask': int(os.environ.get('KEZOHAR_GLOBAL_ASKS_PER_DAY', '3000')),
                  'voice': int(os.environ.get('KEZOHAR_GLOBAL_VOICE_PER_DAY', '600')),
                  'align': int(os.environ.get('KEZOHAR_GLOBAL_ALIGN_PER_DAY', '600')),
                  'food': int(os.environ.get('KEZOHAR_GLOBAL_FOOD_PER_DAY', '800')),
                  'rate': int(os.environ.get('KEZOHAR_GLOBAL_RATE_PER_DAY', '5000')),
                  'tehillim': int(os.environ.get('KEZOHAR_GLOBAL_TEHILLIM_PER_DAY', '200000'))}


TIMING = ROOT / 'data/store/gateway-timing.log'


def timing(kind, status, started, turns=0, question=''):
    """Duration and the question (owner, 2026-10-16: "no privacy needed from now on" — to find what is slow).
    Never the answer or the client's address."""
    try:
        with open(os.open(TIMING, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as log:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind} {status} {round((time.time() - started) * 1000)}ms turns={turns} q={' '.join(question.split())[:300]}\n")
    except OSError:
        pass


def app_key():
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(secrets.token_urlsafe(24))
        os.chmod(KEY_FILE, 0o600)
    return KEY_FILE.read_text().strip()


KEY = app_key()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
hits = defaultdict(deque)
slot = asyncio.Semaphore(3)  # cloud models answer in parallel; the agent itself admits at most 4
waiting = 0


def cors(origin):
    if origin in ORIGINS or (origin or '').startswith(('http://localhost:', 'http://127.0.0.1:', 'http://192.168.')):
        return {'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'content-type, x-kezohar-key, x-kezohar-device', 'Access-Control-Max-Age': '600'}
    return {}


served = defaultdict(deque)
last_sweep = [0.0]


def who(request, kind=''):
    """The device (its random install id) when the app sends one, else the address; and the address itself."""
    address = request.headers.get('cf-connecting-ip') or request.client.host
    device = request.headers.get('x-kezohar-device', '')
    device = device if len(device) == 32 and all(c in '0123456789abcdef' for c in device) else ''
    return (('d:' + device) if device else address) + kind, 'a:' + address + kind, bool(device)


def over(request, kind='ask'):
    """None when allowed; else 'minute' or 'day'. A device: 6 a minute and 150 a day; its address, shared, a wider ceiling."""
    client, address, device = who(request, '' if kind == 'ask' else ':' + kind)
    if device:
        now, q = time.time(), hits[address]
        while q and now - q[0] > 86400:
            q.popleft()
        if len(q) >= ADDRESS_PER_DAY:
            return 'day'
        if sum(1 for t in q if now - t < 60) >= ADDRESS_PER_MINUTE:
            return 'minute'
    reason = limited(client, kind)
    if not reason and device:
        hits[address].append(time.time())
    return reason


def limited(client, kind='ask'):
    """Per client (a minute and a day) and for the whole service (a day): None, 'minute' or 'day'. Clients idle for a day
    are forgotten."""
    now = time.time()
    if now - last_sweep[0] > 3600:  # before this client's entry is taken, so the sweep never drops a count
        last_sweep[0] = now
        for key in [k for k, v in hits.items() if not v or now - v[-1] > 86400]:
            del hits[key]
    q, total = hits[client], served[kind]
    for dq in (q, total):
        while dq and now - dq[0] > 86400:
            dq.popleft()
    if len(total) >= GLOBAL_PER_DAY[kind] or len(q) >= PER_DAY:
        return 'day'
    if sum(1 for t in q if now - t < 60) >= PER_MINUTE:
        return 'minute'
    q.append(now)
    total.append(now)
    return None


# Repeated questions answered at once (2026-10-18, speed at no cost): a question asked again with no conversation before
# it gets the same answer for twelve hours. Never a follow-up, never one tied to the clock or the calendar, never a failure.
import re as _re
from collections import OrderedDict
ANSWERS = OrderedDict()
ANSWER_TTL, ANSWERS_MAX = 12 * 3600, 3000
TIMELY = _re.compile(r'היום|עכשיו|הלילה|מחר|אתמול|השבוע|השנה|מתי|זמן|שעה|שקיעה|זריחה|הדלקת|צאת|כניסת|פרשת|תאריך|לוח|ספירת|עומר|מולד')
CACHEABLE = {'summary-with-quote', 'web-quote-answer', 'model-knowledge', 'llm', 'source-only', 'web-model-answer'}


def _key(question):
    # A fingerprint, never the words (2026-10-20): the answers are kept on disk across restarts, the questions are not.
    import hashlib
    return hashlib.sha256(' '.join(_re.sub(r'[^\u05d0-\u05eaA-Za-z0-9 ]', ' ', question).split()).encode()).hexdigest()[:32]


# Kept across restarts (owner, 2026-10-20), for one version of the agent's code only: a fix (a new commit) starts empty, so
# a corrected answer is never served from before it. Written whole after each new answer (a few MB at most).
ANSWERS_FILE = ROOT / 'data/store/answer-cache.json'


def _code_version():
    try:
        import subprocess
        return subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ''


CODE_VERSION = _code_version()


def _load_answers():
    try:
        saved = json.loads(ANSWERS_FILE.read_text())
    except (OSError, ValueError):
        return
    if saved.get('version') != CODE_VERSION:
        return
    now = time.time()
    for key, (at, result) in saved.get('answers', {}).items():
        if now - at < ANSWER_TTL:
            ANSWERS[key] = (at, result)


def _save_answers():
    try:
        tmp = ANSWERS_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version': CODE_VERSION, 'answers': dict(ANSWERS)}, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        tmp.replace(ANSWERS_FILE)
    except OSError:
        pass


_load_answers()


luna_hits = defaultdict(deque)  # device → times of answers that used the paid model


def cached_forward(question, history=None, spoken=False, tradition=None, free_only=False):
    if spoken:  # corrected upstream first: not matched to a cached question as heard
        return forward(question, history, True, tradition, free_only)
    if history or TIMELY.search(question):
        return forward(question, history, tradition=tradition, free_only=free_only)
    key, now = (tradition or '') + _key(question), time.time()
    hit = ANSWERS.get(key)
    if hit and now - hit[0] < ANSWER_TTL:
        ANSWERS.move_to_end(key)
        return {**hit[1], 'free': True}  # an answer already given costs nothing again
    result = forward(question, history, tradition=tradition, free_only=free_only)
    if result.get('mode') in CACHEABLE and result.get('answer'):
        ANSWERS[key] = (now, result)
        while len(ANSWERS) > ANSWERS_MAX:
            ANSWERS.popitem(last=False)
        _save_answers()
    return result


def forward(question, history=None, spoken=False, tradition=None, free_only=False):
    req = urllib.request.Request(UPSTREAM + '/demo/ask', data=json.dumps({'question': question, 'top_k': 5, 'turns': history or [], 'spoken': bool(spoken), **({'tradition': 'ashkenazi'} if tradition == 'ashkenazi' else {}), **({'free_only': True} if free_only else {})}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.load(r)
    return {'verdict': result.get('verdict'), 'answer': result.get('answer'), 'mode': result.get('mode'), 'bari': result.get('bari'),
            'understood_as': result.get('understood_as'),
            'halachic_verified': result.get('halachic_verified', False),
            'sources': [{'reference': s.get('reference'), 'attribution': s.get('attribution')}
                        for s in (result.get('sources') or [])[:5] if isinstance(s, dict)]}


@app.options('/demo/tehillim')
@app.options('/demo/rate')
@app.options('/demo/food')
@app.options('/demo/align')
@app.options('/demo/speak')
@app.options('/demo/ask')
async def preflight(request: Request):
    headers = cors(request.headers.get('origin'))
    return Response(status_code=204 if headers else 403, headers=headers)


@app.post('/demo/ask')
async def ask(request: Request):
    global waiting
    headers = cors(request.headers.get('origin'))
    if not secrets.compare_digest(request.headers.get('x-kezohar-key', ''), KEY):
        return JSONResponse({'error': 'unauthorized'}, 401, headers=headers)
    reason = over(request)
    if reason:
        return JSONResponse({'error': 'too many questions, try again soon', 'limit': reason}, 429, headers=headers)
    raw = await request.body()
    try:
        body = json.loads(raw) if len(raw) <= 12288 else {}
    except ValueError:
        body = {}
    question = body.get('question', '') if isinstance(body, dict) else ''
    # The iPhone keyboard may open a Hebrew question with an invisible direction mark (U+200F): it hid "מה מברכים על…"
    # from the blessings table (20 s instead of 1). Direction marks are dropped from every question.
    if isinstance(question, str):
        question = question.translate({c: None for c in (0x200e, 0x200f, 0x202a, 0x202b, 0x202c, 0x202d, 0x202e, 0x2066, 0x2067, 0x2068, 0x2069, 0xfeff)})
    history = body.get('turns') if isinstance(body, dict) and isinstance(body.get('turns'), list) else []
    history = [{'q': str(t.get('q', ''))[:300], 'a': str(t.get('a', ''))[:600]} for t in history[-4:] if isinstance(t, dict)]
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        return JSONResponse({'error': 'question required (up to 500 characters)'}, 400, headers=headers)
    if waiting >= QUEUE:
        timing('ask', 503, time.time(), len(history), question)
        return JSONResponse({'error': 'busy, try again in a minute'}, 503, headers=headers)
    waiting += 1
    started = time.time()
    client = who(request)[0]
    luna = luna_hits[client]
    while luna and started - luna[0] > 86400:
        luna.popleft()
    free_only = len(luna) >= LUNA_PER_DAY
    try:
        async with slot:
            result = await asyncio.get_running_loop().run_in_executor(None, cached_forward, question.strip(), history, body.get('spoken') is True if isinstance(body, dict) else False,
                                                                       'ashkenazi' if isinstance(body, dict) and body.get('tradition') == 'ashkenazi' else None, free_only)
    except Exception:
        timing('ask', 502, started, len(history), question)
        return JSONResponse({'error': 'agent unavailable'}, 502, headers=headers)
    finally:
        waiting -= 1
    if result.get('mode') == 'limited':
        timing('ask', 429, started, len(history), question)
        return JSONResponse({'error': 'daily answers used, try again tomorrow', 'limit': 'day'}, 429, headers=headers)
    if not result.get('free') and result.get('mode') not in FREE_MODES:
        luna.append(started)
    timing('ask', 200, started, len(history), question)
    return JSONResponse(result, headers=headers)


@app.post('/demo/speak')
async def speak(request: Request):
    headers = cors(request.headers.get('origin'))
    if not secrets.compare_digest(request.headers.get('x-kezohar-key', ''), KEY):
        return JSONResponse({'error': 'unauthorized'}, 401, headers=headers)
    reason = over(request, 'voice')
    if reason:
        return JSONResponse({'error': 'too many requests, try again soon', 'limit': reason}, 429, headers=headers)
    raw = await request.body()
    try:
        text = json.loads(raw).get('text', '') if len(raw) <= 8192 else ''
    except ValueError:
        text = ''
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        return JSONResponse({'error': 'text required (up to 1200 characters)'}, 400, headers=headers)

    def fetch():
        req = urllib.request.Request(UPSTREAM + '/demo/speak', data=json.dumps({'text': text}).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read()
    try:
        audio = await asyncio.get_running_loop().run_in_executor(None, fetch)
    except Exception:
        return JSONResponse({'error': 'voice unavailable'}, 502, headers=headers)
    return Response(audio, media_type='audio/wav', headers={**headers, 'Cache-Control': 'private, max-age=86400'})


@app.post('/demo/align')
async def align(request: Request):
    """Word timings for a reading already made (/demo/speak), for highlighting each word as it is read."""
    headers = cors(request.headers.get('origin'))
    if not secrets.compare_digest(request.headers.get('x-kezohar-key', ''), KEY):
        return JSONResponse({'error': 'unauthorized'}, 401, headers=headers)
    reason = over(request, 'align')
    if reason:
        return JSONResponse({'error': 'too many requests, try again soon', 'limit': reason}, 429, headers=headers)
    raw = await request.body()
    try:
        text = json.loads(raw).get('text', '') if len(raw) <= 8192 else ''
    except ValueError:
        text = ''
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        return JSONResponse({'error': 'text required'}, 400, headers=headers)

    def fetch():
        req = urllib.request.Request(UPSTREAM + '/demo/align', data=json.dumps({'text': text}).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    try:
        result = await asyncio.get_running_loop().run_in_executor(None, fetch)
    except Exception:
        return JSONResponse({'error': 'no timings'}, 404, headers=headers)
    return JSONResponse(result, headers=headers)


@app.post('/demo/food')
async def food(request: Request):
    """A photo of a plate (a small JPEG, base64) → the foods' names. Its own allowance; the photo is not kept or logged."""
    headers = cors(request.headers.get('origin'))
    if not secrets.compare_digest(request.headers.get('x-kezohar-key', ''), KEY):
        return JSONResponse({'error': 'unauthorized'}, 401, headers=headers)
    reason = over(request, 'food')
    if reason:
        return JSONResponse({'error': 'too many photos, try again soon', 'limit': reason}, 429, headers=headers)
    raw = await request.body()
    if len(raw) > 2_200_000:
        return JSONResponse({'error': 'photo too large'}, 413, headers=headers)

    def fetch():
        req = urllib.request.Request(UPSTREAM + '/demo/food', data=raw, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    started = time.time()
    try:
        result = await asyncio.get_running_loop().run_in_executor(None, fetch)
    except Exception:
        timing('food', 502, started)
        return JSONResponse({'error': 'vision unavailable'}, 502, headers=headers)
    timing('food', 200, started, question=' / '.join(i.get('name', '') for i in result.get('items', [])))
    return JSONResponse({'items': result.get('items', [])[:6], 'not_food': bool(result.get('not_food')), 'product': result.get('product')}, headers=headers)


RATINGS = ROOT / 'data/store/answer-ratings.jsonl'


@app.post('/demo/rate')
async def rate(request: Request):
    """נכון / טעות on an answer (owner, 2026-10-18: "the system must learn from its users"): the question, the answer and the
    verdict, kept on this computer to review and correct — no name, address or device id."""
    headers = cors(request.headers.get('origin'))
    if not secrets.compare_digest(request.headers.get('x-kezohar-key', ''), KEY):
        return JSONResponse({'error': 'unauthorized'}, 401, headers=headers)
    if over(request, 'rate'):
        return JSONResponse({'error': 'too many'}, 429, headers=headers)
    raw = await request.body()
    try:
        body = json.loads(raw) if len(raw) <= 8192 else {}
    except ValueError:
        body = {}
    verdict = body.get('verdict') if isinstance(body, dict) else None
    if verdict not in ('right', 'wrong'):
        return JSONResponse({'error': 'verdict required'}, 400, headers=headers)
    clip = lambda key, n: ' '.join(str(body.get(key, '')).split())[:n]
    row = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'verdict': verdict, 'kind': clip('kind', 30), 'id': clip('id', 80),
           'question': clip('question', 400), 'answer': clip('answer', 1500)}
    try:
        with open(os.open(RATINGS, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as out:
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
    except OSError:
        return JSONResponse({'error': 'not saved'}, 503, headers=headers)
    # An answer called wrong is not given again from the cache: the next asker gets a fresh one (review: review_ratings.py).
    if verdict == 'wrong' and row['question']:
        for tradition in ('', 'ashkenazi'):
            ANSWERS.pop(tradition + _key(row['question']), None)
        _save_answers()
    return JSONResponse({'ok': True}, headers=headers)


TEHILLIM = ROOT / 'data/store/tehillim-count.json'


def _tehillim_today():
    today = time.strftime('%Y-%m-%d')
    try:
        counts = json.loads(TEHILLIM.read_text())
    except (OSError, ValueError):
        counts = {}
    return today, counts


@app.get('/demo/tehillim')
async def tehillim_count(request: Request):
    """עולם אומר תהילים (owner, 2026-10-18): today's chapters said in the app, all together — a number only."""
    today, counts = _tehillim_today()
    return JSONResponse({'date': today, 'chapters': int(counts.get(today, 0))}, headers={**cors(request.headers.get('origin')), 'Cache-Control': 'max-age=30'})


@app.post('/demo/tehillim')
async def tehillim_add(request: Request):
    """Chapters said (1–150 at a time), counted for today; no name, address or device is kept."""
    headers = cors(request.headers.get('origin'))
    if not secrets.compare_digest(request.headers.get('x-kezohar-key', ''), KEY):
        return JSONResponse({'error': 'unauthorized'}, 401, headers=headers)
    if over(request, 'tehillim'):
        return JSONResponse({'error': 'too many'}, 429, headers=headers)
    try:
        chapters = int(json.loads((await request.body())[:200]).get('chapters', 0))
    except (ValueError, TypeError, AttributeError):
        chapters = 0
    if not 1 <= chapters <= 150:
        return JSONResponse({'error': 'chapters 1-150'}, 400, headers=headers)
    today, counts = _tehillim_today()
    counts = {k: v for k, v in counts.items() if k >= time.strftime('%Y-%m-%d', time.localtime(time.time() - 40 * 86400))}
    counts[today] = int(counts.get(today, 0)) + chapters
    TEHILLIM.write_text(json.dumps(counts))
    return JSONResponse({'date': today, 'chapters': counts[today]}, headers=headers)


@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def nothing_else(path: str):
    return JSONResponse({'error': 'not found'}, 404)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8720, access_log=False)
