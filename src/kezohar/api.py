"""Agent API: FastAPI if available, stdlib fallback otherwise. Endpoints: GET /health, POST /search, POST /ask (SSE)."""
import json
import time
import re

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    HAVE_FASTAPI = True
except Exception:
    HAVE_FASTAPI = False

from . import config, fastpath, llm as llm_client
from .agent import Agent

_agent = None
_started = time.time()

def get_agent():
    global _agent
    if _agent is None:
        import os
        store = os.environ.get("STORE_PATH", "data/store/sources.jsonl")
        app_store = os.environ.get("APP_LIBRARY_STORE_PATH", "data/store/app-library/sources.jsonl")
        web_store = os.environ.get("WEB_STORE_PATH", "data/store/web/sources.jsonl")
        _agent = Agent(store_path=[store, web_store])
        from pathlib import Path
        from .library_search import SQLiteLibrarySearch
        from .hybrid import FederatedSearch
        app_db = os.environ.get("APP_LIBRARY_DB_PATH", str(Path(app_store).with_name("library.sqlite3")))
        if Path(app_db).exists():
            _agent.search = FederatedSearch(_agent.search, [SQLiteLibrarySearch(app_db)])
    return _agent

def _validate_ask(body):
    q = (body.get("question") or body.get("q") or "").strip()
    if not q:
        return None, "missing question"
    if len(q) > 2000:
        return None, "question too long"
    return q, ""

# rate limit: simple in-memory token bucket per ip
_hits = {}
def _rate_ok(ip, limit=30, window=60):
    now = time.time()
    arr = _hits.get(ip, [])
    arr = [t for t in arr if now - t < window]
    if len(arr) >= limit:
        _hits[ip] = arr
        return False
    arr.append(now)
    _hits[ip] = arr
    return True

def _ask_result(question, top_k=5, lat=None, lon=None, location=None, research=False):
    if research:
        return get_agent().research(question, top_k=top_k)
    return get_agent().ask(question, top_k=top_k, lat=lat, lon=lon, location=location)

def _sse_events(result):
    # event 1: sources first (<1s target), then answer sentences
    yield "event: sources\n" + "data: " + json.dumps({"sources": result.get("sources", [])}, ensure_ascii=False) + "\n\n"
    ans = result.get("answer", "")
    parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+', ans) if p.strip()]
    for s in parts:
        yield "event: answer\n" + "data: " + json.dumps({"sentence": s}, ensure_ascii=False) + "\n\n"
    yield "event: done\n" + "data: " + json.dumps({"verdict": result.get("verdict"), "mode": result.get("mode"), "elapsed_s": result.get("elapsed_s")}, ensure_ascii=False) + "\n\n"

def _stream_local(question, top_k=5, lat=None, lon=None, location=None):
    """Yield source event before starting inference; retrieved passages are reused."""
    ag = get_agent()
    fast = fastpath.is_out_of_scope(question) or fastpath.handle(question,
        lat=lat or fastpath.DEFAULT_LAT, lon=lon or fastpath.DEFAULT_LON,
        location=location or fastpath.DEFAULT_LOCATION) is not None
    sources = [] if fast else ag.search_only(question,top_k=top_k)
    yield 'event: sources\ndata: '+json.dumps({'sources':sources},ensure_ascii=False)+'\n\n'
    result=ag.ask(question,top_k=top_k,lat=lat,lon=lon,location=location,retrieved_sources=sources)
    events=iter(_sse_events(result))
    next(events)  # Source event was already delivered.
    yield from events

if HAVE_FASTAPI:
    app = FastAPI(title="Kezohar Agent")

    @app.get("/health")
    def health():
        ok, models = llm_client.check_health(config.llm_base_url())
        return {"status": "ok", "uptime_s": round(time.time() - _started, 1),
                "llm_ok": ok, "llm_models": models if ok else [],
                "store_docs": getattr(get_agent().search,"source_count",len(get_agent().search.bm25.docs))}

    @app.post("/search")
    async def search(req: Request):
        body = await req.json()
        q = (body.get("query") or body.get("q") or "").strip()
        if not q:
            return JSONResponse({"error": "missing query"}, status_code=400)
        top_k = int(body.get("top_k", 5))
        return {"results": get_agent().search_only(q, top_k=top_k)}

    @app.post("/research")
    def research(body: dict, req: Request):
        if not _rate_ok(req.client.host if req.client else "?"):
            return JSONResponse({"error": "rate limit"}, status_code=429)
        q, err = _validate_ask(body)
        if err:
            return JSONResponse({"error": err}, status_code=400)
        try:
            limit = max(1, min(int(body.get("top_k", 5)), 8))
        except (TypeError, ValueError):
            return JSONResponse({"error": "invalid top_k"}, status_code=400)
        return get_agent().research(q, top_k=limit)

    @app.post("/ask")
    async def ask(req: Request):
        ip = req.client.host if req.client else "?"
        if not _rate_ok(ip):
            return JSONResponse({"error": "rate limit"}, status_code=429)
        try:
            body = await req.json()
        except Exception:
            return JSONResponse({"error": "bad json"}, status_code=400)
        q, err = _validate_ask(body if isinstance(body, dict) else {})
        if err:
            return JSONResponse({"error": err}, status_code=400)
        stream = body.get("stream", False)
        if stream and body.get('research') is not True:
            return StreamingResponse(_stream_local(q,top_k=int(body.get('top_k',5)),
                lat=body.get('lat'),lon=body.get('lon'),location=body.get('location')),
                media_type='text/event-stream')
        res = _ask_result(q, top_k=int(body.get("top_k", 5)),
                          lat=body.get("lat"), lon=body.get("lon"),
                          location=body.get("location"), research=body.get("research") is True)
        if stream:
            return StreamingResponse(_sse_events(res), media_type="text/event-stream")
        return res
else:
    app = None

def run_stdio_fallback(port=None):
    """Stdlib HTTP fallback when FastAPI is missing (dev only)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = port or config.agent_port()
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def _send(self, code, obj, ctype="application/json"):
            data = obj.encode("utf-8") if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == "/health":
                ok, models = llm_client.check_health(config.llm_base_url())
                self._send(200, {"status": "ok", "llm_ok": ok})
            else:
                self._send(404, {"error": "not found"})
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n).decode("utf-8") if n else "{}"
            try:
                body = json.loads(raw)
            except Exception:
                return self._send(400, {"error": "bad json"})
            if self.path == "/search":
                q = (body.get("query") or "").strip()
                if not q:
                    return self._send(400, {"error": "missing query"})
                return self._send(200, {"results": get_agent().search_only(q)})
            if self.path == "/ask":
                q, err = _validate_ask(body)
                if err:
                    return self._send(400, {"error": err})
                res = _ask_result(q)
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for ev in _sse_events(res):
                        self.wfile.write(ev.encode("utf-8"))
                    return
                return self._send(200, res)
            return self._send(404, {"error": "not found"})
    print(f"kezohar-agent fallback on :{port}")
    HTTPServer(("127.0.0.1", port), H).serve_forever()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("AGENT_PORT", config.agent_port()))
    if HAVE_FASTAPI:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        run_stdio_fallback(port)
