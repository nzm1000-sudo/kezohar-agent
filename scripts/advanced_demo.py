"""Focused actual local examples; reuse existing sources/model, no gold answers."""
import copy,json,os,time
from pathlib import Path
from diagnose_answer import Recorder,VerifierTrace,get_agent,RequestBudget
from kezohar.conversation_updates import browser_turn

def main():
    a=get_agent();a.source_graph=None;a.answer_model=Recorder(a.answer_model);a.source_verifier=VerifierTrace(a.source_verifier)
    rows=[]
    for q,mode,history in [
        ('שולחן ערוך אורח חיים סימן כה סעיף ט','normal',[]),
        ('האם מותר לדבר בין תפילין של יד לתפילין של ראש?','deep',[]),
        ('זה היה בשחרית','normal',['שכחתי יעלה ויבוא בראש חודש']),
        ('בעצם זה היה בערבית','normal',['שכחתי יעלה ויבוא בראש חודש','זה היה בשחרית','כבר סיימתי את התפילה']),
        ('אכלתי ציפס שטיגנו באותו שמן עם שניצלים. אני בשרי?','normal',[])]:
        effective,facts,state=browser_turn(q,history)
        a.answer_model.calls=[];a.source_verifier.checks=[];start=time.perf_counter()
        result=a.converse(effective,circumstances=facts,study_mode=mode,timeout=90 if mode=='deep' else 45,
                          request_budget=RequestBudget(seconds=90 if mode=='deep' else 45),cache_ttl=0)
        row={'question':q,'history':history,'effective_question':effective,'mode':mode,'elapsed_s':round(time.perf_counter()-start,3),
             'result':result,'generation':copy.deepcopy(a.answer_model.calls),'verification':copy.deepcopy(a.source_verifier.checks),
             'human_review':'required','gold_answer':None}
        rows.append(row)
        print(json.dumps({'question':q,'verdict':result['verdict'],'elapsed_s':row['elapsed_s'],
                          'model_calls':len(row['generation']),'answer':result['answer']},ensure_ascii=False),flush=True)
        root=Path('data/store/advanced-research');root.mkdir(exist_ok=True)
        path=root/'live-examples.json';path.write_text(json.dumps(rows,ensure_ascii=False,indent=2));os.chmod(path,0o600)
if __name__=='__main__':main()
