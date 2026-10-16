"""Local cache of public web API answers (Wikipedia, Sefaria…): a repeated lookup costs nothing (owner, 2026-10-16).

Seven days per entry; the whole file never grows past CACHE_MB (300 by default) — the oldest entries go first.
Only public pages and API responses are kept, never questions or answers of users.
"""
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from . import config

DAYS = 7
_lock = threading.Lock()
_db = None


def _conn():
    global _db
    if _db is None:
        path = Path(config.get('WEB_CACHE', 'data/store/web-cache.sqlite3'))
        path.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
        _db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, at REAL, size INTEGER, value TEXT)')
        _db.execute('CREATE INDEX IF NOT EXISTS cache_at ON cache(at)')
    return _db


def key(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _off():
    # Tests exercise the real network path (DNS checks, rate limits): no cache there.
    import os
    return 'PYTEST_CURRENT_TEST' in os.environ or config.get('WEB_CACHE_MB', '300') == '0'


def get(k):
    if _off():
        return None
    with _lock:
        row = _conn().execute('SELECT at, value FROM cache WHERE key=?', (k,)).fetchone()
    if not row or time.time() - row[0] > DAYS * 86400:
        return None
    return json.loads(row[1])


def put(k, value):
    if _off():
        return
    text = json.dumps(value, ensure_ascii=False)
    cap = int(float(config.get('WEB_CACHE_MB', '300')) * 1024 * 1024)
    with _lock:
        db = _conn()
        with db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?,?)', (k, time.time(), len(text), text))
            db.execute('DELETE FROM cache WHERE at < ?', (time.time() - DAYS * 86400,))
            total = db.execute('SELECT COALESCE(SUM(size),0) FROM cache').fetchone()[0]
            if total > cap:
                # The oldest go first until the cache is back under 90% of the cap.
                over = total - int(cap * 0.9)
                for key_, size in db.execute('SELECT key, size FROM cache ORDER BY at').fetchall():
                    if over <= 0:
                        break
                    db.execute('DELETE FROM cache WHERE key=?', (key_,))
                    over -= size


if __name__ == '__main__':
    import os, tempfile
    os.environ['WEB_CACHE'] = tempfile.mktemp(suffix='.sqlite3')
    os.environ['WEB_CACHE_MB'] = '0.001'  # ~1 KB: forces eviction
    put(key('a'), 'x' * 600)
    put(key('b'), 'y' * 600)
    assert get(key('b')) == 'y' * 600 and get(key('a')) is None, 'oldest evicted'
    print('web_cache ok')
