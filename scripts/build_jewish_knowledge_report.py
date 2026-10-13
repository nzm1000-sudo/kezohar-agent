# -*- coding: utf-8 -*-
"""Archive actual traces and present latest recorded answer for each question."""
import collections,gzip,hashlib,html,json
from pathlib import Path

def main():
    files=sorted(Path('data/store/jewish-knowledge-demo').glob('actual-*.jsonl'))
    latest={};manifest=[];archive=Path('docs/jewish-knowledge-artifacts');archive.mkdir(exist_ok=True)
    for file in files:
        raw=file.read_bytes();rows=[json.loads(line) for line in raw.splitlines()]
        for row in rows:
            latest[row['question']]=dict(row,trace_file=file.name)
        (archive/(file.name+'.gz')).write_bytes(gzip.compress(raw,mtime=0))
        manifest.append({'file':file.name+'.gz','uncompressed_sha256':hashlib.sha256(raw).hexdigest(),'records':len(rows)})
    (archive/'manifest.json').write_text(json.dumps(manifest,indent=2))
    rows=list(latest.values());counts=collections.Counter(row['result'].get('verdict') for row in rows)
    summary={'questions':len(rows),'outcomes':dict(counts),'human_reviewed':0,'halachic_verified':0,
        'mean_elapsed_s':round(sum(row['elapsed_s'] for row in rows)/len(rows),3),
        'actual_records_preserved':sum(m['records'] for m in manifest),'notes':'Latest per-question observations may come from different corrective runs; no invented gold answers.'}
    (archive/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    esc=lambda x:html.escape(str(x));sections=[]
    for row in rows:
        r=row['result'];items=[]
        for s in r.get('sources',[]):
            url=s.get('source_url','');link='<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">מקור</a>' if url.startswith('https://') else ''
            items.append('<li>'+esc(s.get('reference',''))+' '+link+'<p>'+esc(s.get('version',''))+'</p></li>')
        sections.append('<section><h2>'+esc(row['question'])+'</h2><p>'+esc(row['elapsed_s'])+' שניות · אינטרנט: '+esc(r.get('internet_used',False))+' · מצב: '+esc(r.get('verdict'))+'</p><p class="answer">'+esc(r.get('answer',''))+'</p><ul>'+''.join(items)+'</ul><details><summary>פלט המודל המקורי</summary><pre>'+esc(json.dumps([g.get('raw_response') for g in row.get('raw_generation',[])],ensure_ascii=False,indent=2))+'</pre></details><details><summary>אימות, אי־ודאות ושגיאות</summary><pre>'+esc(json.dumps({'verification':r.get('verification'),'search_status':r.get('search_status'),'question_intent':r.get('question_intent')},ensure_ascii=False,indent=2))+'</pre></details><small>קובץ הרצה: '+esc(row['trace_file'])+'</small></section>')
    page='<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>עוזר תורני — תשובות בפועל</title><style>body{background:#faf8f2;color:#112e45;font:18px/1.7 system-ui;max-width:1050px;margin:24px auto;padding:0 18px}section{background:white;border:1px solid #ded9cd;border-radius:16px;padding:24px;margin:24px 0}pre{direction:ltr;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.answer{white-space:pre-wrap}a{overflow-wrap:anywhere}</style><h1>עוזר תורני רב־תחומי — תשובות המערכת בפועל</h1><p>לכל שאלה מוצגת התצפית האחרונה שנשמרה; המקורות והפלטים המקוריים מכל ההרצות נשמרו. אין תשובות ייחוס שהומצאו במודל. ציטוט שעבר אימות אינו אישור למשמעות, לשלמות התשובה או לפסיקה הלכתית. מקורות אנציקלופדיים נבדלים מפסוקים ומטא־דאטה ראשוניים.</p><pre>'+esc(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'+''.join(sections)+'<p><a href="jewish-knowledge-artifacts/manifest.json">ארכיונים וגיבובים</a></p></html>'
    Path('docs/JEWISH_KNOWLEDGE_DEMO_2026-10-13.html').write_text(page,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
