"""Actual opt-in local-model/public-API trace; no invented reference answers."""
import copy,json,os,time
from pathlib import Path
from diagnose_answer import Recorder,VerifierTrace,get_agent,RequestBudget

def main():
    agent=get_agent();agent.source_graph=None
    agent.answer_model=Recorder(agent.answer_model);agent.source_verifier=VerifierTrace(agent.source_verifier)
    root=Path('data/store/torah-web-demo');root.mkdir(exist_ok=True);os.chmod(root,0o700)
    path=root/('actual-'+time.strftime('%Y%m%d-%H%M%S')+'.jsonl')
    for q in ('האם מותר לדבר בין תפילין של יד לתפילין של ראש?',
              'מה מברכים על אורז?',
              'ציפס שטוגן באותו שמן שבו טוגנו שניצלים האם צריך להמתין שש שעות?'):
        agent.answer_model.calls=[];agent.source_verifier.checks=[];start=time.perf_counter()
        result=agent.converse(q,research=True,study_mode='deep',timeout=45,cache_ttl=0,request_budget=RequestBudget(seconds=90,max_context_bytes=96000))
        row={'question':q,'result':result,'elapsed_s':round(time.perf_counter()-start,3),
            'raw_generation':copy.deepcopy(agent.answer_model.calls),
            'verifier_trace':copy.deepcopy(agent.source_verifier.checks),'human_review':'required','gold_answer':None}
        with path.open('a',encoding='utf-8') as file:
            os.chmod(path,0o600);file.write(json.dumps(row,ensure_ascii=False)+'\n');file.flush()
        print(json.dumps({'question':q,'verdict':result['verdict'],'elapsed_s':row['elapsed_s'],
            'web_sources':len(result.get('web_findings',[])),'verification':result.get('verification',{}).get('verdict'),
            'answer':result['answer'],'attempts':result.get('discovery_attempts',[])},ensure_ascii=False),flush=True)
    print(str(path),flush=True)
if __name__=='__main__':main()
