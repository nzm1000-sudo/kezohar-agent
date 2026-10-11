"""Read-only index/pack audit. Absence is distinct from restricted permissions."""
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from kezohar.source_quality import classify


def audit(db_path,pack_root):
    p=Path(db_path).resolve()
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
        rows=db.execute("""select json_extract(payload,'$.work_title'),json_extract(payload,'$.tradition'),
            json_extract(payload,'$.license'),count(*),
            sum(case when coalesce(json_extract(payload,'$.metadata.rag_answers_allowed'),1)=1 then 1 else 0 end)
            from records group by 1,2,3 order by 1""").fetchall()
        files=[r[0] for r in db.execute('select key from files')]
    books=[dict(work_title=t,tradition=tr,license=li,chunks=n,rag_available=rag,
                classification=classify({'work_title':t})) for t,tr,li,n,rag in rows]
    packs=[]
    for path in sorted(Path(pack_root).glob('*/manifest.json')):
        d=json.loads(path.read_text())
        packs.append({'pack':path.parent.name,'contains_yalkut_yosef_name':
                      any(w in json.dumps(d,ensure_ascii=False).lower() for w in ('ילקוט יוסף','yalkut yosef','yalkut_yosef'))})
    return {'index_kind':'actual SQLite/FTS5; metadata false blocks RAG, absent flag means eligible',
            'books':books,'total_chunks':sum(b['chunks'] for b in books),
            'rag_available':sum(b['rag_available'] for b in books),
            'sephardi_or_maran_candidates':[b for b in books if b['tradition']=='sephardi'
                 or b['classification']['halachic_authority'] in ('maran','sephardi-posek')],
            'yalkut_yosef_indexed':[b for b in books if 'ילקוט יוסף' in b['work_title']],
            'yalkut_named_files':[f for f in files if 'yalkut' in f.lower() or 'ילקוט' in f],
            'packs':packs,'permission_conclusion':'absence is not a rights denial; no grant scope inferred from model'}


if __name__=='__main__':
    d=audit(ROOT/'data/store/app-library/library.sqlite3',Path('/Users/nitz/Desktop/kazzohar-harakia/public/library/packs'))
    out=ROOT/'docs/LIBRARY_COVERAGE_2026-10-11.json'
    out.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:d[k] for k in ('total_chunks','rag_available','yalkut_yosef_indexed','yalkut_named_files')},ensure_ascii=False))
