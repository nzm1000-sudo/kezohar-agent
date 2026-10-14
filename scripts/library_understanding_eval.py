"""Resumable actual public-question evaluation; no invented reference answers."""
import argparse,copy,json,os,time
from pathlib import Path
from jewish_knowledge_demo import KnowledgeRecorder
from diagnose_answer import get_agent,VerifierTrace,RequestBudget

GROUPS={
'facts':['מי היו חפני ופנחס?','מי היה אביו של משה רבנו?','מי הייתה אמו של שמואל הנביא?',
'כמה בנים היו ליעקב אבינו?','מי כתב את ספר הכוזרי?','מי כתב את מסילת ישרים?',
'מי היה החיד״א?','מה פירוש המילה תיקו בגמרא?','מה ההבדל בין משנה לגמרא?','מי היו בניו של עלי?'],
'ambiguity':['מי היה פנחס?','מי היה פנחס בן אלעזר?','מי היה פנחס בן עלי?',
'מי היו חופני ופינחס?','מי היה רבי יהודה?'],
'interpretation':['מדוע משה רבנו לא נכנס לארץ ישראל?','מה מסמל חלום הסולם של יעקב?',
'מה פירוש שמע ישראל?','מה פירוש אהבת לרעך כמוך?','מה משמעות הביטוי צלם אלוהים?'],
'halacha':['מה מברכים על אורז?','מה מברכים על אגוז פקאן?',
'האם מותר לדבר בין תפילין של יד לתפילין של ראש?',
'שכחתי לברך ברכת המזון ונזכרתי לאחר זמן, מה עושים?',
'צ׳יפס שטוגן בשמן שבו טוגנו שניצלים — האם צריך להמתין שש שעות?'],
'research':['השווה פירושים לכך שמשה לא נכנס לארץ ישראל','חקור את דמותם של חפני ופנחס במקרא ובפרשנות',
'השווה את היחס לכוונה בתפילה במסילת ישרים ובמקורות הלכתיים',
'מה ההבדל בין נבואה לרוח הקודש לפי המקורות?',
'השווה בין פירושים למשמעות מצוות אהבת לרעך כמוך']}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-modes',action='store_true');parser.add_argument('--case',nargs='+');parser.add_argument('--output',default='actual-30.jsonl');args=parser.parse_args()
    root=Path('data/store/library-understanding-2026-10-14');root.mkdir(parents=True,exist_ok=True)
    path=root/('after-modes.jsonl' if args.baseline_modes else Path(args.output).name)
    completed={r['case_id'] for r in (json.loads(line) for line in path.read_text().splitlines())} if path.exists() else set()
    cases=[(f'hophni-{mode}','facts',GROUPS['facts'][0],mode) for mode in ('normal','hybrid','deep')] if args.baseline_modes else [
        (f'{group}-{i+1}',group,q,'deep' if group=='research' else 'normal') for group,questions in GROUPS.items() for i,q in enumerate(questions)]
    import hashlib
    revision=hashlib.sha256(''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('src/kezohar').glob('*.py'))).encode()).hexdigest()
    a=get_agent();a.source_graph=None;a.answer_model=KnowledgeRecorder(a.answer_model);a.source_verifier=VerifierTrace(a.source_verifier)
    for case_id,group,q,mode in cases:
        if case_id in completed or (args.case and case_id not in args.case):continue
        a.answer_model.calls=[];a.source_verifier.checks=[];started=time.perf_counter()
        try:
            result=a.converse(q,study_mode='deep' if mode=='deep' else 'normal',research=mode!='normal',
                request_budget=RequestBudget(seconds=60 if mode=='deep' else 40,
                max_context_bytes=96000 if mode=='deep' else 48000),timeout=30,cache_ttl=0)
        except Exception as exc:
            import traceback
            result={'verdict':'technical_error','answer':'ההרצה נכשלה טכנית.','error_type':type(exc).__name__,'sources':[],
                'error_frames':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)[-8:]]}
        row={'code_fingerprint':revision,'case_id':case_id,'group':group,'question':q,'study_mode':mode,
            'result':result,'elapsed_s':round(time.perf_counter()-started,3),
            'raw_generation':copy.deepcopy(a.answer_model.calls),'verifier_trace':copy.deepcopy(a.source_verifier.checks),
            'model_configured':a.model,'model_calls':len(a.answer_model.calls),
            'clarification_required':bool(result.get('clarifications')) or result.get('verdict')=='identity_ambiguous',
            'gold_answer':None,'expert_labels':None,'human_review':'not-performed',
            'quality_classification':'requires-human-review; software status is not answer correctness'}
        with path.open('a',encoding='utf-8') as file:
            os.chmod(path,0o600);file.write(json.dumps(row,ensure_ascii=False)+'\n');file.flush()
        print(json.dumps({'case_id':case_id,'question':q,'answer':result.get('answer'),'verdict':result.get('verdict'),
            'elapsed_s':row['elapsed_s'],'model_calls':row['model_calls']},ensure_ascii=False),flush=True)
    print(path,flush=True)
if __name__=='__main__':main()
