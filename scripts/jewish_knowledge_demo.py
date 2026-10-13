"""Actual varied Jewish knowledge questions. Local model; public sources only."""
import copy,json,os,time
from pathlib import Path
from diagnose_answer import Recorder,get_agent,RequestBudget

class KnowledgeRecorder(Recorder):
    def generate_knowledge(self,question,sources,timeout=4.5,cancel_event=None):
        row={'question_sent':question,'sources_sent':copy.deepcopy(sources),'task':'knowledge'};self.calls.append(row)
        result=self.delegate.generate_knowledge(question,sources,timeout=timeout,cancel_event=cancel_event)
        row['raw_response']=copy.deepcopy(result);return result

QUESTIONS=['מי היה אביו של משה רבנו?','מי הייתה אמו של שמואל הנביא?','כמה בנים היו ליעקב אבינו?',
    'מי כתב את ספר הכוזרי?','מי היה רבו של רבי מאיר?','מה פירוש המילה תיקו בגמרא?',
    'מי היה החיד״א?','מדוע משה רבנו לא נכנס לארץ ישראל?','מה ההבדל בין משנה לגמרא?','מה מברכים על אורז?',
    'מהן עשר הספירות?','בצע מחקר מעמיק על פירושים לכך שמשה לא נכנס לארץ ישראל',
    'מי היה אבא של משה רבינו?','ומי הייתה אשתו?']

def main():
    a=get_agent();a.source_graph=None;a.answer_model=KnowledgeRecorder(a.answer_model)
    root=Path('data/store/jewish-knowledge-demo');root.mkdir(exist_ok=True);os.chmod(root,0o700)
    path=root/('actual-'+time.strftime('%Y%m%d-%H%M%S')+'.jsonl')
    for index,q in enumerate(QUESTIONS):
        a.answer_model.calls=[];start=time.perf_counter();mode='deep' if index==11 else 'normal'
        history=[QUESTIONS[12]] if index==13 else []
        result=a.converse(q,study_mode=mode,conversation_history=history,
            request_budget=RequestBudget(seconds=90 if mode=='deep' else 45,max_context_bytes=96000 if mode=='deep' else 48000),
            timeout=35,cache_ttl=0)
        row={'question':q,'history':history,'result':result,'elapsed_s':round(time.perf_counter()-start,3),
             'raw_generation':copy.deepcopy(a.answer_model.calls),'gold_answer':None,'human_review':'required'}
        with path.open('a',encoding='utf-8') as file:
            os.chmod(path,0o600);file.write(json.dumps(row,ensure_ascii=False)+'\n');file.flush()
        print(json.dumps({'question':q,'answer':result.get('answer'),'verdict':result.get('verdict'),
            'internet_used':result.get('internet_used',False),'elapsed_s':row['elapsed_s'],'model_calls':len(a.answer_model.calls)},ensure_ascii=False),flush=True)
    print(path,flush=True)
if __name__=='__main__':main()
