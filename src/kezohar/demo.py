"""Private loopback demonstration, using the existing agent and source guards."""
import ipaddress
import time
import os
import json
import threading
import hashlib
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse,Response
from . import api
from .request_budget import RequestBudget
from .source_snapshot import public_sources

app = FastAPI(title='כזוהר הרקיע — הדגמה פרטית')
_audit_lock=threading.Lock()
_requests={}
_requests_lock=threading.Lock()
FEEDBACK_PATH=Path(__file__).resolve().parents[2]/'data/store/private-demo-feedback/issues.jsonl'
SERVER_VERSION=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest()[:12]

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

@app.get('/demo/research-ui.js')
def research_ui():
    return Response((Path(__file__).parent/'static'/'research_ui.js').read_text(encoding='utf-8'),media_type='application/javascript')

@app.get('/demo/status')
def status():
    agent = demo_agent()
    ok, info = agent.answer_model.health(timeout=5)
    from .knowledge_catalog import catalog_status
    from .knowledge_catalog import storage_path
    from .torah_facts import FactSourceStore
    path=storage_path().parent/'source-units.sqlite3'
    learned=FactSourceStore(path).count() if path.exists() else 0
    from .source_registry import registry
    return {'available': ok, 'model': agent.model,'source_registry':registry(),'server_version':SERVER_VERSION,
            'error': '' if ok else str(info), 'retrieval': agent.knowledge.status(),'knowledge_catalog':catalog_status(),
            'learned_source_units':learned}

@app.get('/demo/calendar-reference')
def calendar_reference(date: str):
    import datetime
    from .calendar_reference import compare_netivot
    from .torah_web import ResearchError
    from .request_budget import BudgetExceeded
    try:
        parsed=datetime.date.fromisoformat(date)
        if not 1900<=parsed.year<=2100:raise ValueError('date range')
    except ValueError:return JSONResponse({'error':'נדרש תאריך תקין להשוואת זמני נתיבות.'},status_code=422)
    try:return compare_netivot(parsed,budget=RequestBudget(seconds=18,max_calls=0))
    except (ResearchError,BudgetExceeded,OSError,ValueError):
        return JSONResponse({'error':'ההשוואה החיצונית לא הושלמה; החישוב המקומי אינו מוצג כאימות חיצוני.'},status_code=502)

@app.post('/demo/speak')
async def speak_route(request: Request):
    import asyncio
    from fastapi.responses import Response
    from .speech import speak
    try:
        text=json.loads((await request.body())[:8192]).get('text','')
    except ValueError:
        text=''
    if not isinstance(text,str) or not text.strip():
        return JSONResponse({'error':'text required'},status_code=400)
    audio=await asyncio.get_running_loop().run_in_executor(None,speak,text)
    return Response(audio,media_type='audio/wav') if audio else JSONResponse({'error':'voice unavailable'},status_code=503)

@app.post('/demo/ask')
async def ask(request: Request):
    try:
        body=api._decode_body(await request.body())
        question, opts = api._validate_body(body)
        from .conversation_updates import browser_turn
        from .question_intent import QuestionIntentRouter
        original=question
        question,facts,turn=browser_turn(question,body.get('history',[]),opts['circumstances'])
        from .concept_questions import focused_followup
        focused=focused_followup(original,body.get('history',[]))
        if focused or QuestionIntentRouter().route(original)['engine']=='jewish-knowledge':
            question=focused or original;opts['conversation_history']=body.get('history',[])
            facts=opts['circumstances'];turn={'followup':bool(body.get('history')),'persistent':False,'history_is_evidence':False}
        opts['circumstances']=facts
        token=body.get('request_token')
        import re
        if token is not None and (not isinstance(token,str) or not re.fullmatch('[a-f0-9]{48}',token)):
            raise ValueError('invalid request cancellation token')
    except ValueError as exc:
        return JSONResponse(api._error(str(exc)), status_code=400)
    if opts.pop('stream'):
        return JSONResponse(api._error('ההדגמה מחזירה תשובה מלאה בלבד.'), status_code=400)
    if opts['research'] and body.get('web_consent') is not True:
        return JSONResponse(api._error('חיפוש אינטרנטי דורש בחירה מפורשת במצב משולב והסכמה לשליחת מונחי נושא בלבד.'),status_code=400)
    # No persistent conversation memory. Web discovery sends closed vocabulary
    # only; the full question/history never leaves for a search service.
    import asyncio
    event=threading.Event()
    import secrets
    request_key=token or secrets.token_hex(24)
    with _requests_lock:
        if len(_requests)>=4:return JSONResponse(api._error('ההדגמה עמוסה; נסה שוב לאחר סיום בקשה.'),status_code=429)
        if request_key in _requests:return JSONResponse(api._error('בקשה כבר פעילה.'),status_code=409)
        _requests[request_key]=event
    def run():
        started = time.perf_counter()
        agent = demo_agent()
        deep=opts.get('study_mode')=='deep'
        budget = RequestBudget(seconds=90 if deep else 45,max_context_bytes=96000 if deep else 48000,cancel_event=event)
        result = agent.converse(question, **opts, cache_namespace='private-loopback-demo', request_budget=budget, timeout=45, cache_ttl=0)
        result = dict(result, sources=public_sources(result.get('sources', [])),
                      demo_elapsed_s=round(time.perf_counter()-started, 3),
                      demo_model=agent.model, demo_model_calls=budget.calls)
        result['temporary_conversation']=turn
        result['server_version']=SERVER_VERSION
        return result
    try:return await asyncio.to_thread(run)
    except asyncio.CancelledError:
        event.set();raise
    finally:
        with _requests_lock:
            _requests.pop(request_key,None)

@app.post('/demo/cancel')
async def cancel(request:Request):
    try:
        body=api._decode_body(await request.body())
        if not isinstance(body,dict) or set(body)!={'request_token'}:raise ValueError('cancellation token required')
        token=body['request_token']
        if not isinstance(token,str):raise ValueError('invalid token')
    except ValueError as exc:return JSONResponse(api._error(str(exc)),status_code=400)
    with _requests_lock:
        event=_requests.get(token)
        if event:event.set()
    return {'cancelled':bool(event),'scope':'cooperative; no guarantee of stopping already submitted inference'}

@app.post('/demo/feedback')
async def feedback(request:Request):
    from .review_feedback import record
    try:
        body=api._decode_body(await request.body())
        if not isinstance(body,dict) or set(body)!={'issue','source_ids','answer_digest'}:raise ValueError('anonymous issue fields only')
        if not isinstance(body['source_ids'],list):raise ValueError('source IDs required')
        from .source_snapshot import admissible
        for sid in body['source_ids']:
            current=demo_agent().knowledge.source_by_id(sid) if isinstance(sid,str) else None
            if not current and isinstance(sid,str):
                # Saving an anonymous issue about a public cached identifier is
                # not approval to expose its text or use it as evidence.
                from .torah_facts import FactSourceStore
                project=Path(__file__).resolve().parents[2]
                root=Path(os.environ.get('JEWISH_KNOWLEDGE_ROOT') or project/'data/store/jewish-knowledge').resolve()
                if root!=project and project not in root.parents:raise ValueError('invalid knowledge cache root')
                path=root/'source-units.sqlite3'
                if path.exists():current=FactSourceStore(path).get(sid)
            if not isinstance(sid,str) or not admissible(current or {}):
                raise ValueError('feedback must refer to a current admissible source ID')
        return record(FEEDBACK_PATH,body['issue'],body['source_ids'],body['answer_digest'])
    except ValueError as exc:return JSONResponse(api._error(str(exc)),status_code=400)

# Local sources still use the guarded reader. Web cards link to the public page.
@app.get('/api/sources/{source_id}')
def source_record(source_id: str):
    demo_agent()
    status_code, result = api._source_result(source_id)
    return JSONResponse(result, status_code=status_code)
