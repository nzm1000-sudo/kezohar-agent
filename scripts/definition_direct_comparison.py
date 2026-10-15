"""Diagnostic-only direct generation; outputs never enter the public answer path."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from diagnose_answer import get_agent,RequestBudget
from kezohar import llm
from kezohar.ranking import retrieval_query
from kezohar.retrieval_budget import search_backend
from kezohar.source_snapshot import admissible

root=Path('data/store/explanation-audit-2026-10-15')
baseline=json.loads((root/'http-trace.jsonl').read_text().splitlines()[0])
message=baseline['calls'][0]['request']['messages'][1]['content']
records=json.loads(message.split('מקורות:\n',1)[1].split('\n\n',1)[0])['sources']
a=get_agent();identity=a.answer_model.identity
hits=search_backend(a.search,retrieval_query('נותן טעם בר נותן טעם'),100,RequestBudget(seconds=30))
selected=next(s for s in hits if 'החמץ נתן טעם בכלי, והכלי במרקחת' in s['text'] and admissible(s))
rows=[]
for label,sources in [('B-same-sources',records),('C-reviewed-explanatory-source',[selected])]:
    body={'model':identity.model,'messages':[{'role':'system','content':'הסבר בעברית פשוטה ובקצרה מה פירוש המונח, פתח את ראשי התיבות והוסף דוגמה מתוך המקורות. אל תפסוק למקרה אישי ואל תמציא הפניות. זו בדיקת אבחון בלבד.'},
        {'role':'user','content':json.dumps({'question':baseline['input']['question'],'sources':sources},ensure_ascii=False)}],
        'temperature':0.2,'max_tokens':1000,'reasoning_effort':'none','stream':False}
    started=time.perf_counter();raw=llm._post(identity.base_url,'/chat/completions',body,timeout=45)
    row={'test':label,'request':body,'model_returned':raw.get('model'),
        'visible_output':raw['choices'][0]['message'].get('content'),
        'finish_reason':raw['choices'][0].get('finish_reason'),'usage':raw.get('usage'),
        'elapsed_s':round(time.perf_counter()-started,3),'verified':False,'public_answer':False}
    rows.append(row);print(json.dumps({k:row[k] for k in ('test','visible_output','elapsed_s')},ensure_ascii=False),flush=True)
    path=root/'direct-comparison.json';path.write_text(json.dumps(rows,ensure_ascii=False,indent=2));path.chmod(0o600)
