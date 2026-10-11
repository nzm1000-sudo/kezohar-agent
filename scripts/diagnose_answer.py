"""Private live trace: actual retrieval, generation, verification and display."""
import os
os.environ['SOURCE_GRAPH_ENABLED']='false'
import sys,json,copy,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kezohar.api import get_agent
from kezohar.request_budget import RequestBudget

class Recorder:
    def __init__(self,delegate):self.delegate=delegate;self.calls=[]
    def __getattr__(self,name):return getattr(self.delegate,name)
    def generate(self,question,sources,timeout=4.5):
        row={'question_sent':question,'sources_sent':copy.deepcopy(sources)}
        self.calls.append(row)
        result=self.delegate.generate(question,sources,timeout=timeout)
        row['raw_response']=copy.deepcopy(result)
        return result
class VerifierTrace:
    def __init__(self,delegate):self.delegate=delegate;self.checks=[]
    def __getattr__(self,name):return getattr(self.delegate,name)
    def verify(self,question,answer,sources):
        result=self.delegate.verify(question,answer,sources)
        self.checks.append({'question':question,'raw_answer':answer,'verification':copy.deepcopy(result)})
        return result

def main():
    a=get_agent();a.source_graph=None;a.answer_model=Recorder(a.answer_model);a.source_verifier=VerifierTrace(a.source_verifier)
    q='אדם ששכח לברך ברכת המזון ונזכר לאחר זמן, האם עדיין יכול לברך?'
    rows=[]
    def run(name,question,**kwargs):
        a.answer_model.calls=[];a.source_verifier.checks=[]
        start=time.perf_counter()
        result=a.converse(question,timeout=45,cache_ttl=0,request_budget=RequestBudget(seconds=45),**kwargs)
        row={'name':name,'question':question,'elapsed_s':round(time.perf_counter()-start,3),
             'generation':copy.deepcopy(a.answer_model.calls),'verification':copy.deepcopy(a.source_verifier.checks),
             'result':result}
        rows.append(row)
        print(json.dumps({'name':name,'elapsed_s':row['elapsed_s'],'raw':[c.get('raw_response') for c in row['generation']],
            'verdict':result.get('verdict'),'status':result.get('answer_status'),
            'final':result.get('answer')},ensure_ascii=False),flush=True)
        return result
    first=run('birkat-rule',q)
    if first.get('clarifications'):
        # Explicit synthetic demonstration fact, never inferred from source/model.
        run('birkat-follow-up-not-hungry',q,rule_answers={c['condition_id']:'no' for c in first['clarifications'] if c.get('kind')=='source-condition'})
    run('tefillin','האם מותר לדבר בין תפילין של יד לתפילין של ראש?')
    wrong=[s for s in first.get('sources',[]) if s['source_id']=='0eae057b287626f7']
    if wrong:run('wrong-source-negative','האם מותר לדבר בין תפילין של יד לתפילין של ראש?',retrieved_sources=wrong)
    p=Path('data/store/answer-audit-2026-10-12/after.json')
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({'historical_user_request_raw_output_available':False,'rows':rows},ensure_ascii=False,indent=2))
    os.chmod(p,0o600)

if __name__=='__main__':main()
