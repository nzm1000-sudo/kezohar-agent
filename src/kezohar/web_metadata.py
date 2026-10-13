"""Bounded metadata URL index. Never caches queries, chats or source body text."""
import json
import os
import sqlite3
import time
from pathlib import Path

class WebMetadataIndex:
    def __init__(self,path,max_records=2000,ttl=3600):
        self.path=Path(path);self.max_records=max_records;self.ttl=ttl
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY,payload TEXT NOT NULL,expires REAL NOT NULL)')
        os.chmod(self.path,0o600)
    def connect(self):return sqlite3.connect(str(self.path),timeout=2)
    def remember(self,source):
        metadata=source.get('metadata',{})
        row={k:source.get(k,'') for k in ('source_url','work_title','author','version','license','reference')}
        row.update(page_sha256=metadata.get('page_sha256',''),checked_at=time.time(),
            permission_status=metadata.get('rights_mode','unknown'),
            authority=metadata.get('web_authority',{}))
        with self.connect() as db:
            exists=db.execute('SELECT 1 FROM pages WHERE url=?',(row['source_url'],)).fetchone()
            if not exists and db.execute('SELECT count(*) FROM pages').fetchone()[0]>=self.max_records:return False
            db.execute('INSERT OR REPLACE INTO pages VALUES(?,?,?)',
                (row['source_url'],json.dumps(row,ensure_ascii=False),time.time()+self.ttl))
        return True
    def candidates(self,queries,limit=8):
        from .hebrew import normalize
        # Bounded metadata-only scan, no database/content query propagation.
        words=set(normalize(' '.join(queries)).split());ranked=[]
        with self.connect() as db:
            for payload, in db.execute('SELECT payload FROM pages WHERE expires>? LIMIT ?', (time.time(),self.max_records)):
                row=json.loads(payload);title=normalize(row['work_title']+' '+row['reference'])
                overlap=sum(word in title for word in words)
                if overlap:ranked.append((overlap,row['source_url']))
        return [url for _,url in sorted(ranked,reverse=True)[:limit]]
