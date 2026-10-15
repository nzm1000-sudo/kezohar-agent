"""Public synthetic scenarios against existing local books/model; no medical advice."""
import copy,hashlib,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from diagnose_answer import get_agent,VerifierTrace,RequestBudget
from jewish_knowledge_demo import KnowledgeRecorder
from kezohar.retrieval_budget import search_backend
from kezohar.question_senses import classify

QUESTIONS=['האם מותר לעשות הפריה?','האם מותר לעשות הפריה חוץ־גופית?',
    'האם מותר לעשות הפריה מהזרע והביצית של בני הזוג?',
    'האם מותר להשתמש בתרומת ביצית?','מהי מצוות פרייה ורבייה?',
    'מה מברכים על פירות הארץ?']

def main():
    a=get_agent();a.source_graph=None;a.answer_model=KnowledgeRecorder(a.answer_model)
    a.source_verifier=VerifierTrace(a.source_verifier)
    root=Path('data/store/fertility-relevance-2026-10-15');root.mkdir(parents=True,exist_ok=True)
    # Reproduce old lexical decisions without rolling back or changing the app.
    legacy={ '__name__':'kezohar._audit_prior_ranking','__package__':'kezohar'}
    exec(subprocess.check_output(['git','show','8ea5ea8:src/kezohar/ranking.py']).decode(),legacy)
    prior_query=legacy['retrieval_query'](QUESTIONS[0])
    hits=search_backend(a.search,prior_query,60,RequestBudget(seconds=30))
    (root/'prior-lexical-candidates.json').write_text(json.dumps({'question':QUESTIONS[0],
        'query':str(prior_query),'sources':list(hits),
        'note':'replayed old query against current existing indexes; not historical model output'},ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    revision=hashlib.sha256(''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('src/kezohar').glob('*.py'))).encode()).hexdigest()
    for q in QUESTIONS:
        a.answer_model.calls=[];a.source_verifier.checks=[];started=time.perf_counter()
        result=a.converse(q,request_budget=RequestBudget(seconds=40),timeout=30,cache_ttl=0)
        row={'question':q,'code_fingerprint':revision,'sense':classify(q),'result':result,'elapsed_s':round(time.perf_counter()-started,3),
            'raw_generation':copy.deepcopy(a.answer_model.calls),'verification_trace':copy.deepcopy(a.source_verifier.checks),
            'human_review':'not-performed','halachic_verified':False}
        rows.append(row);print(json.dumps({'question':q,'answer':result.get('answer'),'verdict':result.get('verdict'),
            'elapsed_s':row['elapsed_s'],'model_calls':len(row['raw_generation'])},ensure_ascii=False),flush=True)
        (root/'actual.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        (root/'actual.json').chmod(0o600)
    # A real follow-up must use the selected procedure and avoid repeated questions.
    result=a.converse(QUESTIONS[0],circumstances={'fertility_procedure':'ivf'},
        request_budget=RequestBudget(seconds=40),timeout=30,cache_ttl=0)
    (root/'followup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FOLLOWUP '+json.dumps({'answer':result.get('answer'),'verdict':result.get('verdict')},ensure_ascii=False))

if __name__=='__main__':main()
