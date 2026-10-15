"""Read one published book and re-fetch one anchored unit; no AI or bulk crawl."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kezohar.torah_web import PublicApiTransport,TorahWebReader
from kezohar.torat_emet import BASE,entries,documents
from kezohar.jewish_web import source_from_doc
from kezohar.request_budget import RequestBudget
from kezohar.source_snapshot import admissible

def main():
    started=time.monotonic();budget=RequestBudget(seconds=40)
    transport=PublicApiTransport(max_requests=7)
    root=entries(transport.html(BASE,budget))
    # Select the published Torah/Exodus path by labels, never a guessed file ID.
    path=[]
    for title in ('תורה','שמות','שמות'):
        matches=[r for r in root if r['title']==title]
        if len(matches)!=1:raise ValueError('published catalog label not unique')
        entry=matches[0];path.append(entry)
        html=transport.html(entry['url'],budget)
        root=entries(html)
    docs=documents(html,entry['url'])
    target=[d for d in docs if d['reference']=='שמות פרק-ו-{כ}']
    if len(target)!=1:raise ValueError('explicit requested anchor not unique')
    doc=TorahWebReader(transport).read(target[0]['source_url'],budget)
    source=source_from_doc(doc)
    if not source or not admissible(source):raise ValueError('source not eligible')
    result={'catalog_path':path,'unit_count_in_single_book':len(docs),
        'source':source,'fresh_read_matches':doc==target[0],
        'elapsed_s':round(time.monotonic()-started,3),'requests':transport.calls,
        'semantic_entailment_verified':False,'halachic_verified':False}
    from kezohar.torat_emet import ToratEmetAdapter
    from kezohar.question_intent import QuestionIntentRouter
    question='הסבר על משה בספר שמות מתוך תורת אמת'
    adapter=ToratEmetAdapter(PublicApiTransport(max_requests=8))
    hits=adapter.search(question,QuestionIntentRouter().route(question),RequestBudget(seconds=40))
    result['search']={'question':question,'urls':hits,'attempts':adapter.attempts,'errors':adapter.errors}
    if not hits:raise ValueError('published book search did not return anchored units')
    output=Path('data/store/torat-emet-connection-2026-10-15.json')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    output.chmod(0o600)
    print(json.dumps({'output':str(output),'reference':source['reference'],
        'fresh_read_matches':result['fresh_read_matches'],'requests':transport.calls,
        'elapsed_s':result['elapsed_s'],'text':source['text']},ensure_ascii=False))

if __name__=='__main__':main()
