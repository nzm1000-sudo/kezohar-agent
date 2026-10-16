"""Disk-backed lexical search for the large app corpus; no mock embeddings."""
import json
import sqlite3
from pathlib import Path
from .hebrew import tokens


def rebuild_fts(connection):
    """Initialize once; transactional record triggers maintain incremental updates."""
    if connection.execute("SELECT name FROM sqlite_master WHERE name='library_fts_insert_v2'").fetchone():
        return
    with connection:
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(source_id UNINDEXED, normalized_text, tokenize='unicode61')")
        for name in ('library_fts_insert','library_fts_delete','library_fts_update','library_fts_insert_v2','library_fts_delete_v2','library_fts_update_v2'):
            connection.execute('DROP TRIGGER IF EXISTS '+name)
        connection.execute('DELETE FROM library_fts')
        connection.execute("INSERT INTO library_fts(rowid,source_id,normalized_text) SELECT rowid,id, json_extract(payload, '$.normalized_text') FROM records")
        connection.execute("""CREATE TRIGGER library_fts_insert_v2 AFTER INSERT ON records BEGIN
            INSERT INTO library_fts(rowid,source_id,normalized_text) VALUES(new.rowid,new.id, json_extract(new.payload, '$.normalized_text')); END""")
        connection.execute("""CREATE TRIGGER library_fts_delete_v2 AFTER DELETE ON records BEGIN
            DELETE FROM library_fts WHERE rowid=old.rowid; END""")
        connection.execute("""CREATE TRIGGER library_fts_update_v2 AFTER UPDATE ON records BEGIN
            DELETE FROM library_fts WHERE rowid=old.rowid;
            INSERT INTO library_fts(rowid,source_id,normalized_text) VALUES(new.rowid,new.id, json_extract(new.payload, '$.normalized_text')); END""")


COMMON_WORDS = frozenset('את של על מה זה זו זאת הוא היא הם הן לא כי אם גם או עם אל כל יש אין אשר כמו מן עד רק כן אך אבל '
                          'לו לה בו בה ממנו אותו אותה הזה הזאת היה היתה היו להיות שם לי לך'.split())


class SQLiteLibrarySearch:
    def __init__(self, path, locator_overlay=None):
        self.path = Path(path).resolve()
        self.locator_overlay=locator_overlay

    @property
    def revision(self):
        def signature(path):
            stat=path.stat() if path.exists() else None
            return (stat.st_mtime_ns,stat.st_size,stat.st_ino) if stat else None
        # Active WAL writes need not touch the main database mtime.
        revision=(signature(self.path),signature(Path(str(self.path)+'-wal')))
        if self.locator_overlay is not None:
            # Any review/registry/grant change invalidates answers from prior evidence.
            root=Path(__file__).resolve().parents[2]
            files=[root/'data/locator_resolution_registry.json',root/'data/yalkut_parquet_permission.json',
                   root/'data/store/user-library/approved_resolutions.json']
            # Catalogs can be revoked by editing their file, not just the registry.
            registry=files[0]
            if registry.exists():
                from .locator_resolution import read_json
                entries=read_json(registry,{}).get('resources',[])
                if not isinstance(entries,list):entries=[]
                for entry in entries:
                    if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):continue
                    candidate=(root/entry.get('path','')).resolve()
                    if root in candidate.parents:files.append(candidate)
            return (revision,tuple(p.stat().st_mtime_ns if p.exists() else None for p in files))
        return revision

    @property
    def source_count(self):
        if not self.path.exists():
            return 0
        with sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True) as db:
            return db.execute('SELECT count(*) FROM records').fetchone()[0]

    def search(self, query, top_k=5, request_budget=None):
        if request_budget:request_budget.check('SQLite retrieval')
        terms = list(dict.fromkeys(tokens(query)))
        # Words in almost every passage ("את" is in 121,011 of 746,218) find nothing and made one search rank them
        # all: 1.14 s with "את", 0.05 s without, 8 of the same top 10. Kept when the question has nothing else.
        terms = [t for t in terms if t not in COMMON_WORDS] or terms
        if not terms or not self.path.exists() or top_k<1:
            return []
        # MATCH expression is constructed from quoted tokens; SQL values are bound.
        expression = ' OR '.join('"'+t.replace('"','""')+'"' for t in terms[:50])
        groups=getattr(query,'concept_groups',[])
        focused=' AND '.join('('+' OR '.join('"'+v.replace('"','""')+'"'
            for term in sorted(group) for v in dict.fromkeys([term]+[p+term for p in ('ה','ו','ב','ל','מ')]))+')'
            for group in groups[:8])
        with sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True,
                             timeout=min(5,request_budget.remaining()) if request_budget else 5) as db:
            if request_budget:
                db.set_progress_handler(lambda:1 if request_budget.remaining()<=0 else 0,1000)
            sql='''SELECT records.payload, bm25(library_fts) AS relevance
                FROM library_fts JOIN records ON records.rowid=library_fts.rowid
                WHERE library_fts MATCH ? ORDER BY relevance LIMIT ?'''
            limit=max(1,min(top_k,100))
            rows=db.execute(sql,(focused,limit)).fetchall() if focused else []
            # Very short dual-column food units lack a blessing verb. Retrieve
            # them separately by the explicitly supplied food name, using the
            # existing FTS table; never create another corpus or invent a row.
            subject=getattr(query,'food_subject',None)
            if subject:
                food_expression=' AND '.join('"'+w.replace('"','""')+'"' for w in tokens(subject))
                short=db.execute('''SELECT records.payload,bm25(library_fts) FROM library_fts
                    JOIN records ON records.rowid=library_fts.rowid WHERE library_fts MATCH ?
                    AND length(json_extract(records.payload,'$.text')) <= 600
                    AND instr(json_extract(records.payload,'$.text'),'/') > 0
                    ORDER BY bm25(library_fts) LIMIT 10''',(food_expression,)).fetchall()
                seen={json.loads(payload)['source_id'] for payload,_ in short}
                rows=(short+[(payload,score) for payload,score in rows if json.loads(payload)['source_id'] not in seen])[:limit]
            if request_budget:request_budget.check('SQLite focused retrieval return')
            if len(rows)<limit:
                broad=db.execute(sql,(expression,limit)).fetchall()
                seen={json.loads(payload)['source_id'] for payload,_ in rows}
                rows.extend((payload,score) for payload,score in broad if json.loads(payload)['source_id'] not in seen)
                rows=rows[:limit]
        result=[]
        if request_budget:request_budget.check('SQLite retrieval return')
        for payload, score in rows:
            source=json.loads(payload)
            if self.locator_overlay is not None:source=self.locator_overlay(source)
            source.update(score=-score, search_relevance=-score, backend='app-library-fts5')
            result.append(source)
        return result

    def source_by_id(self, source_id, request_budget=None):
        if request_budget:request_budget.check('SQLite source lookup')
        if not self.path.exists():return None
        with sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,
                             timeout=min(5,request_budget.remaining()) if request_budget else 5) as db:
            if request_budget:db.set_progress_handler(lambda:1 if request_budget.remaining()<=0 else 0,1000)
            row=db.execute('SELECT payload FROM records WHERE id=?',(source_id,)).fetchone()
        if request_budget:request_budget.check('SQLite source lookup return')
        if not row:return None
        source=json.loads(row[0])
        return self.locator_overlay(source) if self.locator_overlay is not None else source

    def lookup_locator(self,hint,request_budget=None):
        from .locator_search import WORKS,matches
        if not self.path.exists():return []
        out=[]
        with sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True) as db:
            if request_budget:db.set_progress_handler(lambda:1 if request_budget.remaining()<=0 else 0,1000)
            names=WORKS[hint['work']];marks=','.join('?' for _ in names)
            rows=db.execute("SELECT id,json_extract(payload,'$.work_title'),json_extract(payload,'$.reference') FROM records WHERE json_extract(payload,'$.work_title') IN ("+marks+")",names)
            for n,(sid,title,reference) in enumerate(rows):
                if request_budget:request_budget.check('locator metadata scan')
                if n>=30000:raise ValueError('locator scan cap exceeded')
                if matches({'work_title':title,'reference':reference},hint):
                    s=self.source_by_id(sid,request_budget)
                    if s:out.append(s)
                if len(out)>=20:break
        return out
