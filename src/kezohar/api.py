"""Agent API: FastAPI if available, stdlib fallback otherwise. Endpoints: GET /health, POST /search, POST /ask (SSE)."""
import json
import time
import re
import math

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    HAVE_FASTAPI = True
except Exception:
    HAVE_FASTAPI = False

from . import config, fastpath, llm as llm_client
from .agent import Agent
from .source_snapshot import public_sources, admissible

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
        user_db = os.environ.get("USER_LIBRARY_DB_PATH", "data/store/user-library/library.sqlite3")
        from .locator_resolution import resolved_source
        backends = [SQLiteLibrarySearch(path,locator_overlay=resolved_source if path==user_db else None) for path in dict.fromkeys((app_db, user_db))
                    if Path(path).exists()]
        if backends:
            _agent.search = FederatedSearch(_agent.search, backends)
        if os.environ.get('SOURCE_GRAPH_ENABLED','').lower() in ('1','true'):
            from .source_graph import HalachicSourceGraph
            _agent.source_graph=HalachicSourceGraph()
    return _agent

def _validate_ask(body):
    if not isinstance(body,dict):return None,'JSON object required'
    q = body.get('question',body.get('q',''))
    if not isinstance(q,str):return None,'question must be a string'
    q=q.strip()
    if not q:
        return None, "missing question"
    if len(q) > 2000:
        return None, "question too long"
    return q, ""

def _decode_body(raw):
    if len(raw)>32000:raise ValueError('request body too large')
    def unique(pairs):
        value={}
        for k,v in pairs:
            if k in value:raise ValueError('duplicate JSON key')
            value[k]=v
        return value
    def bad_constant(value):raise ValueError('non-finite JSON number')
    try:return json.loads(raw,object_pairs_hook=unique,parse_constant=bad_constant)
    except (ValueError,UnicodeError):raise ValueError('bad json') from None

def _validate_body(body, search=False):
    if not isinstance(body,dict):raise ValueError('JSON object required')
    if search:
        q=body.get('query',body.get('q',''))
        if not isinstance(q,str) or not q.strip():raise ValueError('query must be a nonempty string')
        q=q.strip()
        if len(q)>2000:raise ValueError('query too long')
    else:
        q,error=_validate_ask(body)
        if error:raise ValueError(error)
    top=body.get('top_k',5)
    if isinstance(top,str) and top.isascii() and top.isdigit():top=int(top)
    if type(top) is not int or top<1:raise ValueError('invalid top_k')
    opts={'top_k':min(top,100 if search else 8)}
    if not search:
        from .question_understanding import analyze
        analyze(q,body.get('circumstances'))
        opts['circumstances']=body.get('circumstances')
        from .source_rules import validate_answers
        opts['rule_answers']=validate_answers(body.get('rule_answers'))
        for flag in ('stream','research'):
            if type(body.get(flag,False)) is not bool:raise ValueError('invalid '+flag)
            opts[flag]=body.get(flag,False)
        for name,bound in (('lat',90),('lon',180)):
            value=body.get(name)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or abs(value)>bound):
                raise ValueError('invalid '+name)
            opts[name]=value
        location=body.get('location')
        if location is not None and (not isinstance(location,str) or not location.strip() or len(location)>120):
            raise ValueError('invalid location')
        opts['location']=location
    return q,opts

def _error(message):
    return {'error':message,'human_review':'required','halachic_verified':False,
            'verification_status':'not-approved','permissions':'not-checked'}

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

def _ask_result(question, top_k=5, lat=None, lon=None, location=None, research=False, circumstances=None, rule_answers=None):
    result=get_agent().converse(question,circumstances=circumstances,rule_answers=rule_answers,research=research,
                               top_k=top_k,lat=lat,lon=lon,location=location)
    return dict(result,sources=public_sources(result.get('sources',[])))

def _search_result(q,top_k=5):
    from .request_budget import RequestBudget, BudgetExceeded
    from .hybrid import SearchResults
    budget=RequestBudget()
    try:results=get_agent().search_only(q,top_k=top_k,request_budget=budget)
    except BudgetExceeded:
        results=SearchResults([], [{'stage':'retrieval','error':'deadline-exhausted'}])
    return {'results':public_sources(results),'search_status':getattr(results,'status',{'partial':False,'errors':[]}),
            'budget':budget.report(),'halachic_verified':False}

def _source_result(source_id):
    from .permissions import rag_eligible
    if len(source_id)>256:return 400,{'error':'invalid source id'}
    source=get_agent().knowledge.source_by_id(source_id)
    if source is None:return 404,{'error':'source unavailable'}
    if not admissible(source):
        return 409,{'error':'source locator or RAG permission requires review'}
    return 200,{'source':{k:source.get(k,'') for k in ('source_id','work_title','author','reference',
                      'version','text','source_url','attribution','license','verification_status')},
                'human_review':'required','halachic_verified':False}

def _sse_events(result):
    # event 1: sources first (<1s target), then answer sentences
    yield "event: sources\n" + "data: " + json.dumps({"sources": public_sources(result.get("sources", [])),
        'search_status':result.get('search_status',{'partial':False,'errors':[]})}, ensure_ascii=False) + "\n\n"
    if result.get('clarifications'):
        yield 'event: clarification\ndata: '+json.dumps({'clarifications':result['clarifications'],
            'question_analysis':result.get('question_analysis',{})},ensure_ascii=False)+'\n\n'
    ans = result.get("answer", "")
    parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+', ans) if p.strip()]
    for s in parts:
        yield "event: answer\n" + "data: " + json.dumps({"sentence": s}, ensure_ascii=False) + "\n\n"
    yield "event: done\n" + "data: " + json.dumps({"verdict": result.get("verdict"), "mode": result.get("mode"), "elapsed_s": result.get("elapsed_s"),
        'explanation':result.get('explanation'), 'differences':result.get('differences',[]),
        'verification_layers':result.get('verification_layers'),
        'structured_answer':result.get('structured_answer'),
        'answer_status':result.get('answer_status'),
        'answer_policy':result.get('answer_policy'),
        'timings':result.get('timings'),
        'retrieval_metrics':result.get('retrieval_metrics'),
        'known_rule_context':result.get('known_rule_context'),
        'orchestration':result.get('orchestration'),
        'source_relationships':result.get('source_relationships',[]),
        'verification':result.get('verification'), 'search_status':result.get('search_status',{'partial':False,'errors':[]}),
        'error':result.get('error'), 'technical_error':result.get('technical_error'),
        'human_review':result.get('human_review'),'halachic_verified':result.get('halachic_verified')}, ensure_ascii=False) + "\n\n"

def _stream_local(question, top_k=5, lat=None, lon=None, location=None, circumstances=None, rule_answers=None):
    """Yield source event before starting inference; retrieved passages are reused."""
    ag = get_agent()
    from .request_budget import RequestBudget
    budget=RequestBudget()
    from .question_understanding import analyze, effective_question
    analysis=analyze(question,circumstances)
    if analysis['conflicting_fields'] and not fastpath.is_out_of_scope(question):
        yield from _sse_events(ag.converse(question,circumstances=circumstances,rule_answers=rule_answers,request_budget=budget))
        return
    fast = fastpath.is_out_of_scope(question) or fastpath.handle(question,
        lat=lat or fastpath.DEFAULT_LAT, lon=lon or fastpath.DEFAULT_LON,
        location=location or fastpath.DEFAULT_LOCATION) is not None
    effective=effective_question(question,analysis)
    from .request_budget import BudgetExceeded
    try:sources = [] if fast else ag.search_only(effective,top_k=top_k,request_budget=budget)
    except BudgetExceeded:
        yield from _sse_events(ag.converse(question,circumstances=circumstances,rule_answers=rule_answers,request_budget=budget))
        return
    yield 'event: sources\ndata: '+json.dumps({'sources':public_sources(sources),
        'search_status':getattr(sources,'status',{'partial':False,'errors':[]})},ensure_ascii=False)+'\n\n'
    result=ag.converse(question,circumstances=circumstances,rule_answers=rule_answers,top_k=top_k,lat=lat,lon=lon,location=location,retrieved_sources=sources,request_budget=budget)
    events=iter(_sse_events(result))
    next(events)  # Source event was already delivered.
    yield from events

if HAVE_FASTAPI:
    app = FastAPI(title="Kezohar Agent")

    @app.get("/health")
    def health():
        ok, models = get_agent().answer_model.health()
        retrieval = get_agent().knowledge.status()
        return {"status": "ok", "uptime_s": round(time.time() - _started, 1),
                "llm_ok": ok, "llm_models": models if ok else [],
                "store_docs": retrieval["source_count"],
                "retrieval": retrieval}

    @app.post("/search")
    async def search(req: Request):
        try:q,opts=_validate_body(_decode_body(await req.body()),search=True)
        except ValueError as exc:return JSONResponse(_error(str(exc)),status_code=400)
        return _search_result(q,**opts)

    @app.get('/sources/{source_id}')
    def source_record(source_id: str):
        status,result=_source_result(source_id)
        return JSONResponse(result,status_code=status)

    @app.post("/research")
    async def research(req: Request):
        if not _rate_ok(req.client.host if req.client else "?"):
            return JSONResponse({"error": "rate limit"}, status_code=429)
        try:
            q,opts=_validate_body(_decode_body(await req.body()))
        except ValueError as exc:
            return JSONResponse(_error(str(exc)),status_code=400)
        opts.pop('stream');opts['research']=True
        return _ask_result(q,**opts)

    @app.post("/ask")
    async def ask(req: Request):
        ip = req.client.host if req.client else "?"
        if not _rate_ok(ip):
            return JSONResponse({"error": "rate limit"}, status_code=429)
        try:
            q,opts=_validate_body(_decode_body(await req.body()))
        except ValueError as exc:
            return JSONResponse(_error(str(exc)),status_code=400)
        stream=opts.pop('stream')
        if stream and not opts['research']:
            opts.pop('research')
            return StreamingResponse(_stream_local(q,**opts),
                media_type='text/event-stream')
        res = _ask_result(q,**opts)
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
                ok, models = get_agent().answer_model.health()
                self._send(200, {"status": "ok", "llm_ok": ok})
            elif self.path.startswith('/sources/'):
                from urllib.parse import unquote,urlsplit
                status,result=_source_result(unquote(urlsplit(self.path).path[len('/sources/'):]))
                self._send(status,result)
            else:
                self._send(404, {"error": "not found"})
        def do_POST(self):
            try:
                n=int(self.headers.get('Content-Length',0))
                if n<0 or n>32000:raise ValueError('request body too large')
                body=_decode_body(self.rfile.read(n) if n else b'{}')
                if self.path not in ('/search','/ask','/research'):return self._send(404,_error('not found'))
                q,opts=_validate_body(body,search=self.path=='/search')
            except (ValueError,UnicodeError) as exc:
                return self._send(400,_error(str(exc)))
            if self.path == "/search":
                return self._send(200,_search_result(q,**opts))
            if self.path in ('/ask','/research'):
                stream=opts.pop('stream')
                if self.path=='/research':opts['research']=True;stream=False
                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    if not opts['research']:
                        opts.pop('research');output=_stream_local(q,**opts)
                    else:output=_sse_events(_ask_result(q,**opts))
                    for ev in output:
                        self.wfile.write(ev.encode("utf-8"))
                    return
                return self._send(200,_ask_result(q,**opts))
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
