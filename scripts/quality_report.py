"""Exact recorded answers, technical metrics and explicitly limited risk flags."""
import collections, html, json, statistics, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kezohar.source_quality import exclusion_reason
from kezohar.question_understanding import analyze

ROOT=Path('data/store/quality-100-2026-10-13')
SCOPE_REVIEW={
    6:'נבחר כלל לשתיית מים בתוך סעודה; יש לבדוק אם ניתן מענה מספק לשאלה הכללית על מים.',
    24:'נבחר דיון בחליצת תפילין; יש לבדוק אם הוא תומך במישרין בשאלת הנחתן בראש חודש.',
    37:'נבחר סידור רש״י; יש לבדוק כיסוי הזמן ולמה לא נבחר מקור פסיקה ספרדי ישיר.',
    39:'נבחר דיון בתוצאות הפסק בקריאת שמע; יש לבדוק אם הוא מוכיח היתר או איסור דיבור מלכתחילה.',
    59:'נבחר דיון במליחת דגים ובשר; יש לבדוק את התאמתו לשאלת אכילתם יחד.',
}

def load(name):
    p=ROOT/(name+'.jsonl')
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

def flags(row):
    r=row.get('result') or {};v=r.get('verdict');a=r.get('answer','')
    values=[]
    if not r.get('sources') and v not in ('fast','needs_clarification'):values.append('מקור לא נמצא')
    if v=='irrelevant':values.append('מקור לא רלוונטי — נחסם')
    if v in ('unsupported','review_required','insufficient_context','contradicted'):values.append('תמיכה לא הוכחה — נחסם')
    if len(a)>700:values.append('תשובה ארוכה — מעל 700 תווים')
    if v=='no_source' and r.get('sources'):values.append('מועמדים נמצאו; התאמתם לא הוכחה')
    if r.get('clarifications'):values.append('נדרשה הבהרה; נחיצותה טעונה בדיקה')
    if row.get('error') or v in ('budget_exhausted','partial_search','sources-only','technical_error'):values.append('כשל טכני או חיפוש חלקי')
    if v=='fast':values.append('ניתוב לזמן/תאריך; יש לבדוק התאמה לשאלה')
    return values

def source_diagnostics(row):
    """Retrospective current necessary-facet screen, not a halachic judgment."""
    r=row.get('result') or {}
    used={e.get('source_id') for e in r.get('verification',{}).get('evidence',[])}
    return [{'source_id':s['source_id'],'reference':s.get('reference'), 'reason':reason,
             'assessment':'current necessary-facet screen; not historical verdict or halachic review'}
            for s in r.get('sources',[]) if s.get('source_id') in used
            for reason in [exclusion_reason(row['question'],s)] if reason]

def metrics(rows):
    verdicts=collections.Counter((r.get('result') or {}).get('verdict','exception') for r in rows)
    times=sorted(r['elapsed_s'] for r in rows)
    unnecessary_known_fact=sum(any(c.get('field') in analyze(r['question'])['circumstances']
                                  for c in (r.get('result') or {}).get('clarifications',[])) for r in rows)
    return {'questions':len(rows),'citation_checks_passed':sum((r.get('result') or {}).get('verification',{}).get('verdict')=='ok' for r in rows),
            'blocked_or_no_evidence':sum((r.get('result') or {}).get('verdict') in ('no_source','unsupported','invalid_citation','irrelevant','review_required','insufficient_context','contradicted','format_error','rag-scope-pending') for r in rows),
            'clarifications':sum(bool((r.get('result') or {}).get('clarifications')) for r in rows),
            'technical_errors':sum(bool(r.get('error')) or (r.get('result') or {}).get('verdict') in ('budget_exhausted','partial_search','sources-only','technical_error') for r in rows),
            'mean_s':round(statistics.mean(times),3) if times else None,
            'median_s':round(statistics.median(times),3) if times else None,
            'p95_s':times[max(0,int(len(times)*.95)-1)] if times else None,
            'max_s':max(times) if times else None,'verdicts':dict(verdicts),
            'local_model_requests':sum(len(r.get('generation',[])) for r in rows),
            'direct_source_readings':sum((r.get('result') or {}).get('mode')=='direct-source-reading' for r in rows),
            'used_sources_flagged_by_current_facet_screen':sum(bool(source_diagnostics(r)) for r in rows),
            'quality_categories':{
                'source_not_found':{'count':sum(not (r.get('result') or {}).get('sources') and (r.get('result') or {}).get('verdict')=='no_source' for r in rows),'basis':'retrieval result'},
                'source_not_relevant':{'count':sum(bool(source_diagnostics(r)) for r in rows),'basis':'current necessary-facet screen only; not a full semantic relevance assessment'},
                'suitable_source_but_answer_blocked':{'count':None,'basis':'requires human confirmation of source suitability'},
                'long_or_unclear':{'long_over_700_chars':sum(len((r.get('result') or {}).get('answer',''))>700 for r in rows),'unclear_count':None,'basis':'length is measurable; clarity requires human review'},
                'unnecessary_clarification':{'already_supplied_fact_count':unnecessary_known_fact,'other_count':None,'basis':'explicit known facts only; other necessity requires review'},
                'essential_conditions_missing':{'count':None,'basis':'requires source-context review; full quotation is not proof that all case conditions were understood'},
                'source_does_not_support_conclusion':{'count':None,'basis':'general entailment is not certified by this evaluation'}},
            'flags':dict(collections.Counter(f for r in rows for f in flags(r))),
            'human_halachic_approvals':0,'all_results_require_human_review':True}

def main():
    baseline=load('baseline');improved=load('improved');refinement=load('refinement')
    chosen={r['id']:r for r in baseline};chosen.update({r['id']:r for r in improved})
    chosen.update({r['id']:r for r in refinement})
    rows=[chosen[n] for n in sorted(chosen)]
    summary={'baseline':metrics(baseline),'improved':metrics(improved),'refinement':metrics(refinement),'latest':metrics(rows),
             'manual_engineering_scope_review_candidates':SCOPE_REVIEW,
             'not_a_halachic_benchmark':True,'no_gold_answers':True,
             'risk_categories_requiring_human_review':['מקור מתאים אך התשובה נחסמה','הבהרה מיותרת','תנאי מהותי חסר','מקור שאינו תומך במסקנה'],
             'category_counts_can_overlap':True}
    (ROOT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    intro=['# הערכת איכות — 100 שאלות, 2026-10-13','',
           'כל התשובות להלן נוצרו בפועל במערכת המקומית. אין תשובות ייחוס הלכתיות ואין אישור הלכתי אנושי. ציטוט תקין אינו מוכיח את התאמת המסקנה למקרה.',
           'הרצה מקורית ושיפורים נשמרים בנפרד. פלטים גולמיים, הקשר שנשלח למודל, מקורות וטקסטי מקור מלאים נמצאים בקובצי JSONL. בדוח מוצגת התוצאה המאוחרת לכל שאלה; המקורית נשמרת ללא שינוי.',
           'סיווגי אורך, חסימה והבהרה הם מדדי תוכנה. נחיצות הבהרה, מקור מתאים שנחסם, השמטת תנאי ותמיכה במסקנה דורשים ביקורת אנושית; לא נקבע שהם תקינים על סמך חפיפת מילים.','',
           'Qwen המקומי בוחר מזהי מקור או ניסוח תחום לקטלוג. רוב הסברי המקור נבנים בשרת מתוך יחידה מלאה; סיווגי טבלה חד־משמעיים אינם מפעילים מודל. מספר פניות למודל ומצב direct-source-reading מדווחים בנפרד. אין הסקה חופשית שמוצגת כאילו אומתה.','',
           '```json',json.dumps(summary,ensure_ascii=False,indent=2),'```','']
    cards=[]
    comparison=['| סבב | שאלות | אימות ציטוטים | חסימה / אין ראיה | הבהרות | ממוצע בשניות | מעל 700 תווים |',
                '|---|---:|---:|---:|---:|---:|---:|']
    for key,label in [('baseline','בסיס'),('improved','תיקון ראשון'),('refinement','תיקון שני')]:
        m=summary[key]
        comparison.append(f"| {label} | {m['questions']} | {m['citation_checks_passed']} | {m['blocked_or_no_evidence']} | {m['clarifications']} | {m['mean_s']} | {m['quality_categories']['long_or_unclear']['long_over_700_chars']} |")
    intro[4:4]=['','\n'.join(comparison),'','העמודה ״אימות ציטוטים״ אינה שיעור הצלחה הלכתי, ואף אינה הוכחה שהשאלה נענתה במלואה. אפס תוצאות אושרו בידי בודק הלכתי אנושי.','']
    for row in rows:
        r=row.get('result') or {};sources=r.get('sources',[])
        refs='; '.join(s.get('reference','') for s in sources)
        status=(r.get('verification') or {}).get('verdict','לא נבדק')
        answer=r.get('answer') if row.get('result') else 'לא התקבלה תשובת סוכן: '+json.dumps(row.get('error'),ensure_ascii=False)
        raw=[c.get('raw_response') for c in row.get('generation',[])]
        diagnosis=source_diagnostics(row)
        intro += [f"## {row['id']:03} — {row['question']}",'',
                  f"זמן: {row['elapsed_s']} שניות. תוצאה: `{r.get('verdict','exception')}`. אימות ציטוטים: `{status}`. הבהרות: {len(r.get('clarifications',[]))}. Commit: `{row['commit']}`. נדרשת בדיקה הלכתית אנושית.",'',answer or '', '', 'מקורות שנמצאו: '+(refs or 'לא נמצאו'),'',
                  'סיבת אימות: '+str(r.get('verification',{}).get('support','לא בוצע')), '',
                  'סינון נסיבות נוסף בקוד הנוכחי: '+(json.dumps(diagnosis,ensure_ascii=False) if diagnosis else 'לא נמצא כשל בסינון הנסיבות ההכרחי; אין בכך הוכחת תמיכה במסקנה.'),'',
                  'דגלי בדיקה: '+('; '.join(flags(row)) or 'אין דגל תוכנה; אין בכך אישור הלכתי.'),'',
                  'הערת ביקורת: '+SCOPE_REVIEW.get(row['id'],'כל התוצאה טעונה בדיקה הלכתית אנושית.'),'',
                  '<details><summary>פלט המודל המקורי</summary>','', '```json',json.dumps(raw,ensure_ascii=False,indent=2),'```','</details>','']
        source_html=''.join('<details><summary>'+html.escape(s.get('reference',''))+'</summary><p>'+html.escape(s.get('author','')+' · '+s.get('version',''))+'</p><pre>'+html.escape(s.get('text',''))+'</pre></details>' for s in sources)
        cards.append('<article><h2>'+html.escape(f"{row['id']:03} — {row['question']}")+'</h2><p>'+html.escape(f"{row['elapsed_s']} שניות · {r.get('verdict')} · אימות: {status} · הבהרות: {len(r.get('clarifications',[]))} · פניות למודל: {len(row.get('generation',[]))}")+'</p><pre>'+html.escape(answer or '')+'</pre><p>נדרשת בדיקה הלכתית אנושית.</p><p>'+html.escape(SCOPE_REVIEW.get(row['id'],''))+'</p>'+source_html+'<details><summary>פלט המודל המקורי — אינו פסיקה</summary><pre>'+html.escape(json.dumps(raw,ensure_ascii=False,indent=2))+'</pre></details></article>')
    Path('docs/QUALITY_100_2026-10-13.md').write_text('\n'.join(intro))
    Path('docs/QUALITY_100_2026-10-13.html').write_text('<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>100 שאלות — תוצאות בפועל</title><style>body{background:#faf8f2;color:#112e45;font:17px/1.7 system-ui;max-width:1000px;margin:auto;padding:20px}article{background:white;border:1px solid #ded9cd;border-radius:16px;padding:20px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}summary{cursor:pointer}h2{font-size:21px}</style><h1>100 שאלות — תשובות בפועל</h1><p>אימות תוכנה אינו אישור הלכתי. כל התוצאות טעונות בדיקה אנושית. אין תשובות ייחוס שניחש מודל.</p><details><summary>מדדים טכניים</summary><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></details>'+''.join(cards)+'</html>')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
