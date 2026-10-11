"""User-authorized live walkthroughs, with explicitly artificial follow-up facts.

No prepared answers: every result comes from the loopback demonstration service.
"""
import json
from pathlib import Path
import time
import tempfile
import urllib.request

CASES = [
    ('צ׳יפס שטוגן בשמן שבו טוגנו שניצלים — האם צריך להמתין שש שעות?',
     [{'next_food':'dairy','oil_residue':'absent'}]),
    ('שכחתי לומר יעלה ויבוא בראש חודש — האם חוזרים?',
     [{'prayer_service':'shachrit','prayer_stage':'finished'}]),
    ('האם מותר לחמם בשבת מרק שהתקרר?',
     [{'soup_cooked':'fully','soup_temperature':'cold'}, {'reheating_method':'hotplate'}]),
    ('מה מברכים על אגוז פקאן?', [{'blessing_stage':'before'}]),
    ('האם מותר לדבר בין תפילין של יד לתפילין של ראש?', []),
]
root=Path(__file__).resolve().parents[1]/'data/store/demo-phase5-2026-10-12'
root.mkdir(parents=True,exist_ok=True)
run=Path(tempfile.mkdtemp(prefix='run-',dir=root))
rows=[]
for question,followups in CASES:
    row={'question':question,'followup_facts_are_demonstration_only':True,'turns':[]}
    facts={}
    for update in [{}]+followups:
        facts.update(update)
        start=time.perf_counter()
        req=urllib.request.Request('http://127.0.0.1:8711/demo/ask',
             data=json.dumps({'question':question,'circumstances':facts,'top_k':5},ensure_ascii=False).encode(),
             headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=65) as response:result=json.load(response)
        row['turns'].append({'supplied_facts':dict(facts),'wall_elapsed_s':round(time.perf_counter()-start,3),'result':result})
        print(json.dumps({'question':question,'facts':facts,'answer':result.get('answer'),
            'verdict':result.get('verdict'),'time':result.get('demo_elapsed_s'),
            'calls':result.get('demo_model_calls'),
            'sources':[(s.get('work_title'),s.get('reference')) for s in result.get('sources',[])],
            'verification':result.get('verification',{}).get('support')},ensure_ascii=False),flush=True)
    rows.append(row)
    (run/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))

print('תוצאות ההדגמה נשמרו: '+str(run/'results.json'),flush=True)
