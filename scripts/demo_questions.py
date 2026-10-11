"""Five explicit user-approved live questions against the loopback demo only."""
import json
from pathlib import Path
import urllib.request
import time
QUESTIONS=[
'צ׳יפס שטוגן בשמן שבו טוגנו שניצלים — האם צריך להמתין שש שעות?',
'שכחתי לומר יעלה ויבוא בראש חודש — האם חוזרים?',
'האם מותר לחמם בשבת מרק שהתקרר?',
'מה מברכים על אגוז פקאן?',
'האם מותר לדבר בין תפילין של יד לתפילין של ראש?']
rows=[]
path=Path(__file__).resolve().parents[1]/'data/store/demo-2026-10-12/results.json'
for question in QUESTIONS:
    started=time.perf_counter()
    req=urllib.request.Request('http://127.0.0.1:8711/demo/ask',
        data=json.dumps({'question':question,'top_k':5},ensure_ascii=False).encode(),
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=65) as response: result=json.load(response)
    except Exception as exc:
        result={'error':type(exc).__name__,'answer':'הבקשה לא הושלמה; אין תשובה מאומתת.'}
    rows.append({'question':question,'wall_elapsed_s':round(time.perf_counter()-started,3),'result':result})
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(json.dumps({'question':question,'answer':result.get('answer'),'elapsed_s':result.get('demo_elapsed_s'),
        'verdict':result.get('verdict'),'model_calls':result.get('demo_model_calls'),
        'sources':[(s.get('work_title'),s.get('reference')) for s in result.get('sources',[])],
        'error':result.get('error')},ensure_ascii=False),flush=True)
