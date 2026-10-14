"""Bounded repeatable public-source expansion; no model or private questions."""
import argparse,json,sys,time
from urllib.parse import quote
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kezohar.knowledge_catalog import storage_path
from kezohar.torah_facts import FactSourceStore
from kezohar.jewish_web import JewishKnowledgeWebSearch
from kezohar.question_intent import QuestionIntentRouter
from kezohar.request_budget import RequestBudget,BudgetExceeded
from kezohar.torah_web import PublicApiTransport

PLANS={'chasidut':('הסבר על תניא','הסבר על ליקוטי מוהר״ן','הסבר על קדושת לוי','הסבר על נועם אלימלך'),
       'kabbalah':('הסבר על ספר יצירה','הסבר על עץ חיים','הסבר על זוהר','הסבר על הצמצום בקבלה'),
       'stories':('סיפור מתוך סיפורי מעשיות','סיפורי צדיקים בשבחי הבעש״ט'),
       'musar':('הסבר על מסילת ישרים','הסבר על חובות הלבבות','הסבר על אהבת ישראל','הסבר על ביטחון'),
       'halacha':('הלכות תפילין מתוך שולחן ערוך','הלכות שבת מתוך שולחן ערוך','הלכות כשרות מתוך שולחן ערוך')}
ANCHORS={'chasidut':'Tanya, Part I; Likkutei Amarim 1:1',
         'kabbalah':'Sefer Yetzirah 1:2','musar':'Mesillat Yesharim 1','stories':'Sippurei Maasiyot 1:2'}

def expand(domains,web=None,store=None,budget=None,positions=None):
    web=web or JewishKnowledgeWebSearch(transport=PublicApiTransport(max_requests=18))
    store=store or FactSourceStore(storage_path().parent/'source-units.sqlite3')
    budget=budget or RequestBudget(seconds=120,max_calls=0)
    results=[];seen=set();positions=dict(positions or {});next_positions=dict(positions)
    for domain in domains:
        budget.check('knowledge expansion domain')
        position=positions.get(domain,0)
        if type(position) is not int or not 0<=position<=100000:raise ValueError('invalid expansion position')
        index=position%len(PLANS[domain]);q=PLANS[domain][index];route=QuestionIntentRouter().route(q)
        discovered=web.search(q,route,budget,limit=2)
        anchor=ANCHORS.get(domain) if index==0 else None
        urls=([('https://www.sefaria.org/'+quote(anchor.replace(' ','_')))] if anchor else [])+discovered
        for url in list(dict.fromkeys(urls))[:2]:
            if url in seen:continue
            seen.add(url);budget.check('knowledge expansion read')
            try:
                s=web.read(url,budget)
                if not s:results.append({'domain':domain,'url':url,'status':'permission-or-version-not-established'});continue
                store.remember(s)
                saved=store.get(s['source_id'])
                results.append({'domain':domain,'source_id':s['source_id'],'reference':s['reference'],
                    'version':s['version'],'license':s['license'],'url':url,
                    'genre':s['metadata'].get('knowledge_genre'),'status':'indexed-public-unit' if saved else 'store-limit',
                    'halachic_verified':False,'source_snapshot':s['metadata']['page_sha256']})
            except BudgetExceeded:raise
            except Exception as e:results.append({'domain':domain,'url':url,'status':'blocked','reason':type(e).__name__})
        next_positions[domain]=position+1
    return {'sources':results,'errors':web.errors,'budget':budget.report(),'model_calls':0,'automatic_rulings':False,
            'next_positions':next_positions}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--domains',nargs='+',choices=list(PLANS),default=list(PLANS));args=p.parse_args()
    root=storage_path().parent;progress=root/'expansion-progress.json'
    positions=json.loads(progress.read_text()) if progress.exists() else {}
    result=expand(args.domains,positions=positions)
    path=root/('expansion-'+time.strftime('%Y%m%d-%H%M%S')+'.json')
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary=progress.with_suffix('.tmp');temporary.write_text(json.dumps(result['next_positions']));temporary.replace(progress)
    print(json.dumps(result,ensure_ascii=False,indent=2));print(path)
