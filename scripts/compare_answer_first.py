"""Actual local-only before/after demonstration, no prepared model outputs."""
import argparse,copy,json,os,time
from pathlib import Path
from diagnose_answer import Recorder,VerifierTrace,get_agent,RequestBudget
QUESTIONS=[
 ('tefillin','האם מותר לדבר בין תפילין של יד לתפילין של ראש?'),
 ('birkat','שכחתי לברך ברכת המזון, מה עושים?'),
 ('pecan','מה מברכים על פקאן?'),
 ('soup','האם מותר לחמם בשבת מרק שהתקרר?'),
 ('yaaleh','שכחתי לומר יעלה ויבוא בראש חודש — האם חוזרים?'),
]
def main():
 parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['before','after']);parser.add_argument('--only',choices=[n for n,q in QUESTIONS]);opts=parser.parse_args()
 p=Path('data/store/answer-first-2026-10-12')/(opts.phase+(('-'+opts.only) if opts.only else '')+'.json')
 if p.exists():raise FileExistsError('Do not overwrite recorded live output')
 a=get_agent();a.source_graph=None;a.answer_model=Recorder(a.answer_model);a.source_verifier=VerifierTrace(a.source_verifier)
 rows=[]
 for name,q in QUESTIONS:
  if opts.only and name!=opts.only:continue
  a.answer_model.calls=[];a.source_verifier.checks=[];start=time.perf_counter()
  result=a.converse(q,timeout=45,cache_ttl=0,request_budget=RequestBudget(seconds=45))
  row={'name':name,'question':q,'elapsed_s':round(time.perf_counter()-start,3),
       'generation':copy.deepcopy(a.answer_model.calls),'verification':copy.deepcopy(a.source_verifier.checks),'result':result}
  rows.append(row)
  print(json.dumps({'name':name,'elapsed_s':row['elapsed_s'],'verdict':result['verdict'],
   'clarifications':len(result.get('clarifications',[])),'answer':result['answer'],
   'sources':[(s['source_id'],s['reference']) for s in result.get('sources',[])]},ensure_ascii=False),flush=True)
 p.parent.mkdir(parents=True,exist_ok=True);os.chmod(p.parent,0o700)
 p.write_text(json.dumps({'phase':opts.phase,'rows':rows},ensure_ascii=False,indent=2));os.chmod(p,0o600)
if __name__=='__main__':main()
