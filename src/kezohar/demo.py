"""Private loopback demonstration, using the existing agent and source guards."""
import ipaddress
import time
import os
import json
import threading
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from . import api
from .request_budget import RequestBudget
from .source_snapshot import public_sources

app = FastAPI(title='כזוהר הרקיע — הדגמה פרטית')
_audit_lock=threading.Lock()

class _AuditedModel:
    def __init__(self, delegate, path):
        self.delegate,self.path=delegate,path
    def __getattr__(self,key):return getattr(self.delegate,key)
    def generate(self,question,sources,timeout=4.5):
        from .source_snapshot import fingerprint
        started=time.perf_counter()
        result=self.delegate.generate(question,sources,timeout=timeout)
        row={'question':question,'model':self.identity.model,
             'sources':[{'source_id':s['source_id'],'snapshot':fingerprint(s)} for s in sources],
             'raw_response':result,'elapsed_s':round(time.perf_counter()-started,3),
             'status':'unverified-model-output; not a ruling'}
        with _audit_lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            os.chmod(self.path.parent,0o700)
            with self.path.open('a',encoding='utf-8') as file:
                os.chmod(self.path,0o600)
                file.write(json.dumps(row,ensure_ascii=False)+'\n')
        return result

def demo_agent():
    os.environ['SOURCE_GRAPH_ENABLED']='false'  # This private process only.
    agent=api.get_agent()
    # Demo retrieval is read-only; co-retrieval proposals must not mutate the
    # active source graph. This changes only this demo process, not config files.
    agent.source_graph=None
    # Opt-in trace only for the authorized demonstration. Ordinary UI use does
    # not persist questions or model output; nothing raw is returned publicly.
    raw=os.environ.get('DEMO_AUDIT_PATH')
    if raw and not isinstance(agent.answer_model,_AuditedModel):
        root=Path(__file__).resolve().parents[2]/'data/store/demo-phase5-2026-10-12'
        path=Path(raw).resolve()
        if path.parent!=root:raise ValueError('demo audit path must remain in isolated demo directory')
        with _audit_lock:
            if not isinstance(agent.answer_model,_AuditedModel):agent.answer_model=_AuditedModel(agent.answer_model,path)
    return agent

@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0]
    try:
        allowed = ipaddress.ip_address(host).is_loopback and request.client.host in ('127.0.0.1', '::1')
    except ValueError:
        allowed = False
    origin = request.headers.get('origin')
    expected = str(request.base_url).rstrip('/')
    if not allowed or (origin and origin != expected):
        return JSONResponse({'error': 'הגישה מותרת רק מכתובת ההדגמה המקומית.'}, status_code=403)
    if request.method == 'POST' and not request.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'error': 'נדרש קלט JSON.'}, status_code=415)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response

@app.get('/', response_class=HTMLResponse)
def home():
    return (Path(__file__).parent / 'static' / 'demo.html').read_text(encoding='utf-8')

@app.get('/demo/status')
def status():
    agent = demo_agent()
    ok, info = agent.answer_model.health(timeout=5)
    return {'available': ok, 'model': agent.model,
            'error': '' if ok else str(info), 'retrieval': agent.knowledge.status()}

@app.post('/demo/ask')
async def ask(request: Request):
    try:
        question, opts = api._validate_body(api._decode_body(await request.body()))
    except ValueError as exc:
        return JSONResponse(api._error(str(exc)), status_code=400)
    if opts.pop('research') or opts.pop('stream'):
        return JSONResponse(api._error('ההדגמה משתמשת בספרייה המקומית בלבד.'), status_code=400)
    # No saved conversation memory, persistent changes, web research or old cache.
    import asyncio
    def run():
        started = time.perf_counter()
        agent = demo_agent()
        budget = RequestBudget(seconds=45)
        result = agent.converse(question, **opts, cache_namespace='private-loopback-demo', request_budget=budget, timeout=45, cache_ttl=0)
        result = dict(result, sources=public_sources(result.get('sources', [])),
                      demo_elapsed_s=round(time.perf_counter()-started, 3),
                      demo_model=agent.model, demo_model_calls=budget.calls)
        return result
    return await asyncio.to_thread(run)

# Expose only the existing guarded source reader, not web research or memory.
@app.get('/api/sources/{source_id}')
def source_record(source_id: str):
    demo_agent()
    status_code, result = api._source_result(source_id)
    return JSONResponse(result, status_code=status_code)
