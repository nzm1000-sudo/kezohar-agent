"""Append-only private evaluation against the existing local corpus and model."""
import argparse,copy,datetime,hashlib,json,os,subprocess,time
from pathlib import Path
from diagnose_answer import Recorder,VerifierTrace,get_agent,RequestBudget
CASES=[
 ('blessings','מה מברכים על פקאן?'),
 ('prayer','שכחתי לומר יעלה ויבוא בראש חודש — האם חוזרים?'),
 ('shabbat','האם מותר לחמם בשבת מרק שהתקרר?'),
 ('kashrut','האם צריך להטביל כלי זכוכית חדשים?'),
 ('meat-milk','ציפס שטוגן בשמן שבו טוגנו שניצלים — צריך להמתין שש שעות?'),
 ('festivals','האם אישה חייבת בהדלקת נרות חנוכה?'),
 ('tefillin','מותר לדבר בין תפילין של יד לשל ראש?'),
 ('purity','האם מותר לטבול ביום?'),
 ('money','מצאתי כסף ברחוב, האם מותר לי לקחת?'),
 ('meal-blessing','שכחתי לברך ברכת המזון, מה עושים?'),
]
def main():
 p=argparse.ArgumentParser();p.add_argument('cycle');p.add_argument('--domains',nargs='+');p.add_argument('--repeat',type=int,default=1);p.add_argument('--circumstances');args=p.parse_args()
 circumstances=json.loads(args.circumstances) if args.circumstances else None
 if not 1<=args.repeat<=3:p.error('repeat must be 1..3')
 if not args.cycle.replace('-','').isalnum():p.error('simple cycle name required')
 root=Path('data/store/autonomous-evaluation');root.mkdir(parents=True,exist_ok=True);os.chmod(root,0o700)
 path=root/(args.cycle+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.jsonl')
 commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 diff=subprocess.check_output(['git','diff','HEAD','--','src'])
 code_state={'base_commit':commit,'uncommitted_core_changes':bool(diff),'working_diff_sha256':hashlib.sha256(diff).hexdigest()}
 a=get_agent();a.source_graph=None;a.answer_model=Recorder(a.answer_model);a.source_verifier=VerifierTrace(a.source_verifier)
 with path.open('x') as f:
  os.chmod(path,0o600)
  for iteration in range(args.repeat):
   for domain,q in CASES:
    if args.domains and domain not in args.domains:continue
    a.answer_model.calls=[];a.source_verifier.checks=[];start=time.perf_counter()
    result=a.converse(q,timeout=45,cache_ttl=0,request_budget=RequestBudget(seconds=45),circumstances=circumstances,cache_namespace='evaluation-'+args.cycle)
    row={'cycle':args.cycle,'iteration':iteration,'commit':commit,'code_state':code_state,'domain':domain,'question':q,
         'elapsed_s':round(time.perf_counter()-start,3),'generation':copy.deepcopy(a.answer_model.calls),
         'verification':copy.deepcopy(a.source_verifier.checks),'result':result,
         'user_circumstances':circumstances,'human_halachic_review':'required','gold_halachic_answer':None}
    f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    print(json.dumps({'domain':domain,'elapsed_s':row['elapsed_s'],'verdict':result['verdict'],
        'sources':[(s['source_id'],s['reference']) for s in result.get('sources',[])],
        'answer':result['answer']},ensure_ascii=False),flush=True)
 print('EVALUATION_PATH='+str(path),flush=True)
if __name__=='__main__':main()
