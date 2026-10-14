"""Build a private report from actual records; never invent quality scores."""
import argparse,collections,html,json,statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--commit',required=True);args=parser.parse_args()
    path=ROOT/'data/store/library-understanding-2026-10-14'/Path(args.input).name
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if len(rows)!=30 or len({r['case_id'] for r in rows})!=30:raise SystemExit('Require 30 completed distinct cases')
    if len({r['code_fingerprint'] for r in rows})!=1:raise SystemExit('Mixed source fingerprints')
    verdicts=collections.Counter(r['result'].get('verdict','unknown') for r in rows)
    times=sorted(r['elapsed_s'] for r in rows)
    summary={'commit':args.commit,'questions':30,'verdict_counts':dict(verdicts),
        'typed_fact_support':sum(bool(r['result'].get('fact_verified')) for r in rows),
        'source_linked_proposals':sum(r['result'].get('verdict')=='knowledge_explanation' for r in rows),
        'citation_check_ok':sum(r['result'].get('verification',{}).get('verdict')=='ok' for r in rows),
        'technical_errors':sum(r['result'].get('verdict')=='technical_error' for r in rows),
        'clarifications':sum(r['clarification_required'] for r in rows),
        'partial_search':sum(bool(r['result'].get('search_status',{}).get('partial')) for r in rows),
        'model_calls':sum(r['model_calls'] for r in rows),'human_approved':0,
        'elapsed_s':{'min':times[0],'max':times[-1],'mean':round(statistics.mean(times),3),
                     'median':round(statistics.median(times),3),'p95_nearest_rank':times[28]},
        'gold_answers':'not provided','semantic_correctness':'not independently graded',
        'input':str(path.relative_to(ROOT))}
    reasons=collections.Counter(e.get('reason',e.get('error','unknown')) for r in rows
        for e in r['result'].get('search_status',{}).get('errors',[]) if e.get('stage')=='knowledge-generation')
    summary['generation_rejection_reasons']=dict(reasons)
    path.with_suffix('.summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape
    out=['<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>30 שאלות — תוצאות בפועל</title><style>body{font:17px/1.7 system-ui;color:#173348;background:#faf8f2;max-width:1000px;margin:auto;padding:24px}article{background:white;border:1px solid #ddd6c5;padding:24px;border-radius:16px;margin:18px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}li{margin:8px 0}.answer{white-space:pre-wrap;font-size:19px}.warning{background:#f6eedb;padding:14px}a{color:#174d7a}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:right;border-bottom:1px solid #ded9cc}</style>',
        '<h1>30 שאלות — תשובות המערכת בפועל</h1>',
        '<p class="warning">אימות ציטוטים הוא מדד תוכנה. אפס תשובות אושרו בידי בודק אנושי במסגרת הרצה זו. פרפרזה או היסק מוצע אינם משמעות שהוכחה. כל התוצאות טעונות הערכת איכות עצמאית; אין תשובות ייחוס מומצאות.</p>',
        '<p>Commit: <code>'+esc(args.commit)+'</code>. הפלטים הגולמיים וכל הקשר המודל נשמרו מקומית.</p>',
        '<details><summary>מדדי תוכנה וזמנים</summary><pre>'+esc(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details>',
        '<table><tr><th>שאלה</th><th>מצב תוכנה</th><th>שניות</th><th>מודל</th></tr>']
    for i,r in enumerate(rows,1):
        out.append(f'<tr><td><a href="#q{i}">{esc(r["question"])}</a></td><td>{esc(r["result"].get("verdict",""))}</td><td>{r["elapsed_s"]}</td><td>{r["model_calls"]}</td></tr>')
    out.append('</table>')
    for i,r in enumerate(rows,1):
        d=r['result'];out.extend([f'<article id="q{i}"><h2>{i}. {esc(r["question"])}</h2>',
            '<div class="answer">'+esc(d.get('answer',''))+'</div>',
            '<p>זמן: '+str(r['elapsed_s'])+' שניות · פניות למודל: '+str(r['model_calls'])+
            ' · מצב: '+esc(d.get('verdict',''))+' · הבהרה: '+('כן' if r['clarification_required'] else 'לא')+'</p>',
            '<p>אישור אנושי: לא בוצע. חיפוש חלקי: '+('כן' if d.get('search_status',{}).get('partial') else 'לא')+'</p>',
            '<h3>המקורות שהוצגו בתשובה</h3><ul>'])
        for s in d.get('sources',[]):
            label=' · '.join(str(s.get(k,'')) for k in ('work_title','reference','version') if s.get(k))
            out.append('<li>'+esc(label)+'<details><summary>טקסט המקור שהוחזר</summary><pre>'+esc(s.get('text',''))+'</pre></details></li>')
        out.append('</ul><details><summary>מועמדי גילוי, טענות ואימות</summary><pre>')
        audit={'selected_source_ids':[s['source_id'] for s in d.get('sources',[])],
            'discovery_sources':[{'source_id':s['source_id'],'reference':s['reference'],'version':s.get('version')}
                for s in d.get('knowledge_discovery',{}).get('sources',[])],
            'claims':d.get('claims',[]),'verification':d.get('verification'),
            'verification_layers':d.get('verification_layers'),'search_status':d.get('search_status'),
            'orchestration':d.get('orchestration')}
        out.append(esc(json.dumps(audit,ensure_ascii=False,indent=2))+'</pre></details>')
        out.append('<details><summary>פלטי המודל המקוריים לפני האימות</summary><pre>'+esc(json.dumps(r['raw_generation'],ensure_ascii=False,indent=2))+'</pre></details></article>')
    out.append('<p>הפלטים נשמרו כפי שהתקבלו, כולל חסימות, שגיאות ניסוח וקטעים לא מועילים. מועמדי הגילוי מוגבלים לתקציבי השליפה של המוצר; אין כאן טענה שהמערכת קראה את כל הספרייה.</p></html>')
    dest=ROOT/'docs/LIBRARY_30_ACTUAL_2026-10-14.html';dest.write_text('\n'.join(out),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2));print(dest)

if __name__=='__main__':main()
