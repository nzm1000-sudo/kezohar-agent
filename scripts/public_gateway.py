"""Public gateway: the only door from the internet (via Cloudflare Tunnel) to the local agent.

Listens on 127.0.0.1:8720. Exposes POST /demo/ask and /demo/speak (an answer read aloud) only, requires the app key, limits size and rate per client,
allows three answers at a time with a short queue, forwards to the loopback agent (127.0.0.1:8711) and returns only
the answer fields the app shows. Question text is never written to disk or logs.
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
                'Access-Control-Allow-Headers': 'content-type, x-kezohar-key', 'Access-Control-Max-Age': '600'}
    return {}


def limited(client):
    now, q = time.time(), hits[client]
    while q and now - q[0] > 86400:
        q.popleft()
    if len(q) >= PER_DAY or sum(1 for t in q if now - t < 60) >= PER_MINUTE:
        return True
    q.append(now)
    return False


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
    client = request.headers.get('cf-connecting-ip') or request.client.host
    if limited(client):
        return JSONResponse({'error': 'too many questions, try again soon'}, 429, headers=headers)
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
        return JSONResponse({'error': 'busy, try again in a minute'}, 503, headers=headers)
    waiting += 1
    try:
        async with slot:
            result = await asyncio.get_running_loop().run_in_executor(None, forward, question.strip(), history)
    except Exception:
        return JSONResponse({'error': 'agent unavailable'}, 502, headers=headers)
    finally:
        waiting -= 1
    return JSONResponse(result, headers=headers)


@app.post('/demo/speak')
async def speak(request: Request):
    headers = cors(request.headers.get('origin'))
    if not secrets.compare_digest(request.headers.get('x-kezohar-key', ''), KEY):
        return JSONResponse({'error': 'unauthorized'}, 401, headers=headers)
    client = (request.headers.get('cf-connecting-ip') or request.client.host) + ':voice'
    if limited(client):
        return JSONResponse({'error': 'too many requests, try again soon'}, 429, headers=headers)
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


@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def nothing_else(path: str):
    return JSONResponse({'error': 'not found'}, 404)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8720, access_log=False)
