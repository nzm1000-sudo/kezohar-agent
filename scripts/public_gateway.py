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
# An internet address may be shared by a whole home, yeshiva or phone company (owner, 2026-10-18), so the allowance is
# per device (the app's random install id); the address keeps only a wide ceiling, against one caller inventing devices.
ADDRESS_PER_MINUTE, ADDRESS_PER_DAY = 40, 2000
# The whole service's daily ceiling, whatever the address (security review 2026-10-18: the app key is public, so a caller
# changing addresses could run up the paid models' bill): questions, readings aloud and word timings.
GLOBAL_PER_DAY = {'ask': int(os.environ.get('KEZOHAR_GLOBAL_ASKS_PER_DAY', '3000')),
                  'voice': int(os.environ.get('KEZOHAR_GLOBAL_VOICE_PER_DAY', '600')),
                  'align': int(os.environ.get('KEZOHAR_GLOBAL_ALIGN_PER_DAY', '600'))}


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
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
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


def forward(question, history=None):
    req = urllib.request.Request(UPSTREAM + '/demo/ask', data=json.dumps({'question': question, 'top_k': 5, 'turns': history or []}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.load(r)
    return {'verdict': result.get('verdict'), 'answer': result.get('answer'), 'mode': result.get('mode'), 'bari': result.get('bari'),
            'understood_as': result.get('understood_as'),
            'halachic_verified': result.get('halachic_verified', False),
            'sources': [{'reference': s.get('reference'), 'attribution': s.get('attribution')}
                        for s in (result.get('sources') or [])[:5] if isinstance(s, dict)]}


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
    history = body.get('turns') if isinstance(body, dict) and isinstance(body.get('turns'), list) else []
    history = [{'q': str(t.get('q', ''))[:300], 'a': str(t.get('a', ''))[:600]} for t in history[-4:] if isinstance(t, dict)]
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        return JSONResponse({'error': 'question required (up to 500 characters)'}, 400, headers=headers)
    if waiting >= QUEUE:
        timing('ask', 503, time.time(), len(history), question)
        return JSONResponse({'error': 'busy, try again in a minute'}, 503, headers=headers)
    waiting += 1
    started = time.time()
    try:
        async with slot:
            result = await asyncio.get_running_loop().run_in_executor(None, forward, question.strip(), history)
    except Exception:
        timing('ask', 502, started, len(history), question)
        return JSONResponse({'error': 'agent unavailable'}, 502, headers=headers)
    finally:
        waiting -= 1
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


@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def nothing_else(path: str):
    return JSONResponse({'error': 'not found'}, 404)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8720, access_log=False)
