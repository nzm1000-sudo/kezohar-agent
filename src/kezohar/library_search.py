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


class SQLiteLibrarySearch:
    def __init__(self, path, locator_overlay=None):
        self.path = Path(path).resolve()
        self.locator_overlay=locator_overlay

    @property
    def revision(self):
        revision=self.path.stat().st_mtime_ns if self.path.exists() else None
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

    def search(self, query, top_k=5):
        terms = list(dict.fromkeys(tokens(query)))
        if not terms or not self.path.exists() or top_k<1:
            return []
        # MATCH expression is constructed from quoted tokens; SQL values are bound.
        expression = ' OR '.join('"'+t.replace('"','""')+'"' for t in terms[:50])
        with sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True) as db:
            rows = db.execute('''SELECT records.payload, bm25(library_fts) AS relevance
                FROM library_fts JOIN records ON records.rowid=library_fts.rowid
                WHERE library_fts MATCH ? ORDER BY relevance LIMIT ?''', (expression, max(1,min(top_k,100)))).fetchall()
        result=[]
        for payload, score in rows:
            source=json.loads(payload)
            if self.locator_overlay is not None:source=self.locator_overlay(source)
            source.update(score=-score, search_relevance=-score, backend='app-library-fts5')
            result.append(source)
        return result

    def source_by_id(self, source_id):
        if not self.path.exists():return None
        with sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT payload FROM records WHERE id=?',(source_id,)).fetchone()
        if not row:return None
        source=json.loads(row[0])
        return self.locator_overlay(source) if self.locator_overlay is not None else source
