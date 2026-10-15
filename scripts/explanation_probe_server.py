"""Finite, opt-in trace for the public explanation audit, never general logging.

Launch instead of scripts/demo.py during the authorized probe. Only exact
public questions/history listed here are recorded; normal demo has no recorder.
No provider URL, environment, authorization header or model reasoning is saved.
"""
import contextvars,hashlib,json,sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kezohar import llm
from kezohar.demo import app
import uvicorn

QUESTIONS={'מה זה אומר נט בר נט?','תסביר יותר פשוט ותן דוגמה','מהו כלי בן יומו?',
    'מה זה נ"ט בר נ"ט?','מה פירוש נ״ט בר נ״ט?','מי היה אביו של משה רבנו?',
    'האם מותר לעשות הפריה?','מה פירוש המונח הסינתטי זטזטזט?',
    'האם מותר לבשל בשר עם חלב?','האם מותר לבשל דגים בסיר בשרי בן יומו?'}
ROOT=Path(__file__).resolve().parents[1]/'data/store/explanation-audit-2026-10-15'
ROOT.mkdir(parents=True,exist_ok=True);ROOT.chmod(0o700)
ACTIVE=contextvars.ContextVar('authorized_public_probe',default=None)
LOCK=threading.Lock();POST=llm._post

def traced_post(base,path,body,**kwargs):
    row=ACTIVE.get()
    if row is None:return POST(base,path,body,**kwargs)
    call={'provider':'openai-compatible','path':path,'request':body,
        'started_epoch':time.time(),'started':True,'completed':False}
    row['calls'].append(call);started=time.perf_counter()
    try:
        result=POST(base,path,body,**kwargs)
        call.update(completed=True,usage=result.get('usage'),
            model_returned=result.get('model'),choices=[{'finish_reason':c.get('finish_reason'),
                'visible_content':c.get('message',{}).get('content')} for c in result.get('choices',[])])
        return result
    except Exception as exc:
        call['error_type']=type(exc).__name__;raise
    finally:call.update(ended_epoch=time.time(),elapsed_s=round(time.perf_counter()-started,3))

llm._post=traced_post

class PublicProbe:
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method')!='POST' or scope.get('path')!='/demo/ask':
            return await app(scope,receive,send)
        chunks=[]
        while True:
            message=await receive();chunks.append(message)
            if message['type']!='http.request' or not message.get('more_body'):break
        raw=b''.join(m.get('body',b'') for m in chunks)
        try:body=json.loads(raw)
        except (ValueError,TypeError):body={}
        history=body.get('history',[])
        allowed=(body.get('question') in QUESTIONS and isinstance(history,list)
            and all(q in QUESTIONS for q in history) and not body.get('circumstances') and not body.get('rule_answers'))
        public_input={k:body[k] for k in ('question','history','study_mode','research') if k in body}
        row={'input':public_input,'calls':[],'started_epoch':time.time()} if allowed else None
        token=ACTIVE.set(row);sent=[];index=0
        async def replay():
            nonlocal index
            if index<len(chunks):m=chunks[index];index+=1;return m
            return await receive()
        async def capture(message):
            if row is not None and message['type']=='http.response.body':sent.append(message.get('body',b''))
            await send(message)
        try:await app(scope,replay,capture)
        finally:
            ACTIVE.reset(token)
            if row is not None:
                try:row['display_response']=json.loads(b''.join(sent))
                except ValueError:row['display_response']='non-JSON response'
                row['ended_epoch']=time.time()
                with LOCK:
                    file=ROOT/'http-trace.jsonl'
                    with file.open('a',encoding='utf-8') as out:
                        file.chmod(0o600);out.write(json.dumps(row,ensure_ascii=False)+'\n')

if __name__=='__main__':uvicorn.run(PublicProbe(),host='127.0.0.1',port=8711)
