"""A copy of Sefaria's Hebrew texts on the NAS (owner, 2026-10-21: "if Sefaria disappears…"), from its official public
export (https://storage.googleapis.com/sefaria-export/): every Hebrew version and the merged one per book, the schemas and
the table of contents. Each version file keeps its own `license` field — what the app may show is decided per text.
Polite (4 at a time), resumable (a file of the right size is not fetched again). Writes only under its target folder.

Usage: sefaria_mirror.py <target folder>
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = 'https://storage.googleapis.com/storage/v1/b/sefaria-export/o'
FILES = 'https://storage.googleapis.com/sefaria-export/'
target = Path(sys.argv[1])


def listing(prefix):
    out, token = [], None
    while True:
        q = {'prefix': prefix, 'fields': 'items(name,size),nextPageToken', 'maxResults': '1000'}
        if token:
            q['pageToken'] = token
        d = json.load(urllib.request.urlopen(f'{BUCKET}?{urllib.parse.urlencode(q)}', timeout=60))
        out += [(it['name'], int(it['size'])) for it in d.get('items', [])]
        token = d.get('nextPageToken')
        if not token:
            return out


def fetch(item):
    name, size = item
    path = target / name
    if path.exists() and path.stat().st_size == size:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(FILES + urllib.parse.quote(name), timeout=120) as r:
                data = r.read()
            tmp = path.with_suffix(path.suffix + '.part')
            tmp.write_bytes(data)
            tmp.replace(path)
            return len(data)
        except Exception:
            time.sleep(5 * (attempt + 1))
    print('failed', name, flush=True)
    return 0


files = [f for f in listing('json/') if '/Hebrew/' in f[0]] + listing('schemas/') + listing('table_of_contents.json')
print(len(files), 'files', round(sum(s for _, s in files) / 1e9, 2), 'GB', flush=True)
done = got = 0
with ThreadPoolExecutor(4) as pool:
    for n in pool.map(fetch, files):
        done += 1
        got += n
        if done % 500 == 0:
            print(f'{done}/{len(files)} files, {round(got / 1e9, 2)} GB this run', flush=True)
print(f'mirror done: {done} files, {round(got / 1e9, 2)} GB this run', flush=True)
