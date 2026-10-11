"""Disk-backed lexical search for the large app corpus; no mock embeddings."""
import json
import sqlite3
from pathlib import Path
from .hebrew import tokens


def rebuild_fts(connection):
    """Initialize once; transactional record triggers maintain incremental updates."""
    if connection.execute("SELECT name FROM sqlite_master WHERE name='library_fts_insert'").fetchone():
        return
    with connection:
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(source_id UNINDEXED, normalized_text, tokenize='unicode61')")
        connection.execute('DELETE FROM library_fts')
        connection.execute("INSERT INTO library_fts SELECT id, json_extract(payload, '$.normalized_text') FROM records")
        connection.execute("""CREATE TRIGGER library_fts_insert AFTER INSERT ON records BEGIN
            INSERT INTO library_fts VALUES(new.id, json_extract(new.payload, '$.normalized_text')); END""")
        connection.execute("""CREATE TRIGGER library_fts_delete AFTER DELETE ON records BEGIN
            DELETE FROM library_fts WHERE source_id=old.id; END""")
        connection.execute("""CREATE TRIGGER library_fts_update AFTER UPDATE ON records BEGIN
            DELETE FROM library_fts WHERE source_id=old.id;
            INSERT INTO library_fts VALUES(new.id, json_extract(new.payload, '$.normalized_text')); END""")


class SQLiteLibrarySearch:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def search(self, query, top_k=5):
        terms = list(dict.fromkeys(tokens(query)))
        if not terms or not self.path.exists() or top_k<1:
            return []
        # MATCH expression is constructed from quoted tokens; SQL values are bound.
        expression = ' OR '.join('"'+t.replace('"','""')+'"' for t in terms[:50])
        with sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True) as db:
            rows = db.execute('''SELECT records.payload, bm25(library_fts) AS relevance
                FROM library_fts JOIN records ON records.id=library_fts.source_id
                WHERE library_fts MATCH ? ORDER BY relevance LIMIT ?''', (expression, max(1,min(top_k,100)))).fetchall()
        result=[]
        for payload, score in rows:
            source=json.loads(payload)
            source.update(score=-score, search_relevance=-score, backend='app-library-fts5')
            result.append(source)
        return result
