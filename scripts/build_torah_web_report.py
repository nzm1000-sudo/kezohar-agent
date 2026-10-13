"""Local review artifact from actual saved runs; never generates a gold answer."""
import gzip,hashlib,html,json
from pathlib import Path

def main():
    files=sorted(Path('data/store/torah-web-demo').glob('actual-*.jsonl'))
    if not files:raise SystemExit('no actual traces')
    rows=[json.loads(line) for line in files[-1].read_text().splitlines()]
    esc=lambda value:html.escape(str(value))
    archive=Path('docs/torah-web-artifacts');archive.mkdir(exist_ok=True)
    manifest=[]
    for file in files:
        raw=file.read_bytes();out=archive/(file.name+'.gz');out.write_bytes(gzip.compress(raw,mtime=0))
        manifest.append({'file':out.name,'sha256':hashlib.sha256(raw).hexdigest(),'records':len(raw.splitlines())})
    (archive/'manifest.json').write_text(json.dumps(manifest,indent=2))
    sections=[]
    for row in rows:
        r=row['result'];items=[]
        approved={e['source_id'] for e in r.get('verification',{}).get('evidence',[])}
        for s in r.get('sources',[])+r.get('web_findings',[]):
            url=s.get('source_url','');link=('<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">עמוד מקור</a>') if url.startswith('https://') else ''
            items.append('<li><b>'+esc(s.get('reference',''))+'</b> '+link+'<p>'+esc('ציטוט שעבר אימות תוכנה' if s['source_id'] in approved else 'מועמד לעיון בלבד; לא אישור לפסיקה')+'</p></li>')
        raw=[g.get('raw_response',{}) for g in row.get('raw_generation',[])]
        sections.append('<section><h2>'+esc(row['question'])+'</h2><p>'+esc(row['elapsed_s'])+' שניות · אימות: '+esc(r.get('verification',{}).get('verdict'))+' · חיפוש חלקי: '+esc(r.get('search_status',{}).get('partial',False))+'</p><h3>תשובת הסוכן בפועל</h3><p class="answer">'+esc(r.get('answer',''))+'</p><h3>מקורות וקישורים</h3><ul>'+''.join(items)+'</ul><details><summary>פלט Qwen לפני האימות</summary><pre>'+esc(json.dumps(raw,ensure_ascii=False,indent=2))+'</pre></details><details><summary>סיבת האימות או החסימה</summary><pre>'+esc(json.dumps(r.get('verification',{}),ensure_ascii=False,indent=2))+'</pre></details></section>')
    page='<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>מחקר אינטרנטי — תוצאות בפועל</title><style>body{background:#faf8f2;color:#112e45;font:18px/1.7 system-ui;margin:24px auto;padding:0 18px;max-width:1000px}section{background:white;border:1px solid #ded9cd;border-radius:16px;padding:24px;margin:24px 0}pre{direction:ltr;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.answer{white-space:pre-wrap}a{overflow-wrap:anywhere}</style><h1>מחקר אינטרנטי — תוצאות אמיתיות</h1><p>כל התוצאות טעונות בדיקה הלכתית אנושית. אימות ציטוט אינו אישור למסקנה או להחלתה על מקרה אישי. לא נוצרה תשובת ייחוס הלכתית.</p><p>הרצה: '+esc(files[-1].name)+'</p>'+''.join(sections)+'<p><a href="torah-web-artifacts/manifest.json">כל הרצות המקור והגיבובים</a></p></html>'
    Path('docs/TORAH_WEB_DEMO_2026-10-13.html').write_text(page,encoding='utf-8')
    print('docs/TORAH_WEB_DEMO_2026-10-13.html')
if __name__=='__main__':main()
