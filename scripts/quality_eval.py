"""Durable, resumable actual local evaluation. No halachic reference answers."""
import argparse, copy, hashlib, json, os, subprocess, time
from pathlib import Path
from diagnose_answer import Recorder, VerifierTrace, get_agent, RequestBudget

QUESTIONS = Path(__file__).with_name('quality_questions.txt')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('run', choices=['baseline', 'improved', 'refinement'])
    p.add_argument('--ids', nargs='*', type=int)
    args = p.parse_args()
    questions = QUESTIONS.read_text().splitlines()
    assert len(questions) == len(set(questions)) == 100
    root = Path('data/store/quality-100-2026-10-13')
    root.mkdir(parents=True, exist_ok=True); os.chmod(root, 0o700)
    path = root / (args.run+'.jsonl')
    identity = {'commit': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                'questions_sha256': hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()}
    previous=[json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    completed={r['id'] for r in previous}
    if len(completed)!=len(previous):p.error('duplicate recorded IDs; preserve file and investigate')
    if any(r['questions_sha256']!=identity['questions_sha256'] or r['question']!=questions[r['id']-1] for r in previous):
        p.error('question fixture changed; do not mix evaluation inputs')
    if previous and len(completed)<100 and any(r['commit']!=identity['commit'] for r in previous):
        p.error('code changed during a resumable run; use a separate refinement run')
    a = get_agent(); a.source_graph = None
    a.answer_model = Recorder(a.answer_model); a.source_verifier = VerifierTrace(a.source_verifier)
    with path.open('a') as f:
        os.chmod(path, 0o600)
        for n, q in enumerate(questions, 1):
            if n in completed or (args.ids and n not in args.ids): continue
            a.answer_model.calls=[]; a.source_verifier.checks=[]; start=time.perf_counter()
            try:
                result=a.converse(q,timeout=45,cache_ttl=0,request_budget=RequestBudget(seconds=45),
                                  cache_namespace='quality-100-'+args.run)
                error=None
            except Exception as exc:
                # Continue remaining questions; do not manufacture an agent answer.
                result=None; error={'type':type(exc).__name__, 'detail':str(exc)}
            row=dict(identity,id=n,question=q,elapsed_s=round(time.perf_counter()-start,3),
                     answer_model=a.model,
                     generation=copy.deepcopy(a.answer_model.calls),verification=copy.deepcopy(a.source_verifier.checks),
                     result=result,error=error,human_halachic_review='required',gold_halachic_answer=None)
            f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush(); os.fsync(f.fileno())
            print(json.dumps({'id':n,'elapsed_s':row['elapsed_s'],'verdict':(result or {}).get('verdict'),
                              'clarifications':len((result or {}).get('clarifications',[])), 'error':error},ensure_ascii=False),flush=True)
    print('EVALUATION_PATH='+str(path),flush=True)

if __name__=='__main__': main()
