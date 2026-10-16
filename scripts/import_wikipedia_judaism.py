"""Hebrew Wikipedia's Judaism articles into the user library (owner, 2026-10-16: "the agent should know everything").

Stage `titles`: category members from Judaism roots, 3 levels deep, at most 20,000 articles.
Stage `articles`: each article's plain text (MediaWiki API, ~4 requests a second, a descriptive User-Agent), cut
into paragraphs and inserted as records (licence CC BY-SA 4.0, attribution to Wikipedia and the article's URL).
Resumable: rerun to continue. Then build the dense index: scripts/build_vector_index.py on the user library.
"""
import json
import re
import sqlite3
import sys
import time
import hashlib
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
OUT = ROOT / 'data/store/wikipedia-judaism'
API = 'https://he.wikipedia.org/w/api.php'
UA = 'KezoharAgent/1.0 (Jewish learning app; contact nizoza369@gmail.com)'
ROOTS = ['יהדות', 'הלכה', 'תנ"ך', 'תלמוד', 'משנה', 'מועדי ישראל', 'תפילות יהודיות', 'מצוות', 'מנהגים יהודיים',
         'רבנים', 'חכמי המשנה והתלמוד', 'ראשונים', 'אחרונים', 'ספרות רבנית', 'קבלה', 'חסידות', 'מחשבת ישראל',
         'היסטוריה של עם ישראל', 'בית המקדש', 'דמויות מקראיות', 'מושגים ביהדות', 'כשרות', 'שבת']
MAX_ARTICLES = 20000


def api(params):
    url = API + '?' + urllib.parse.urlencode({**params, 'format': 'json', 'formatversion': 2})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=20) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 * (attempt + 1))
    return {}


def titles():
    OUT.mkdir(parents=True, exist_ok=True)
    seen_cats, pages, frontier = set(), {}, [('קטגוריה:' + r, 0) for r in ROOTS]
    while frontier and len(pages) < MAX_ARTICLES:
        cat, depth = frontier.pop(0)
        if cat in seen_cats:
            continue
        seen_cats.add(cat)
        cont = {}
        while True:
            data = api({'action': 'query', 'list': 'categorymembers', 'cmtitle': cat, 'cmlimit': 500, 'cmtype': 'page|subcat', **cont})
            for m in (data.get('query') or {}).get('categorymembers', []):
                if m['ns'] == 14 and depth < 3:
                    frontier.append((m['title'], depth + 1))
                elif m['ns'] == 0:
                    pages.setdefault(m['title'], cat)
            time.sleep(0.25)
            if 'continue' not in data:
                break
            cont = data['continue']
        print(f'{len(pages)} articles · {len(seen_cats)} categories', flush=True)
    (OUT / 'titles.json').write_text(json.dumps(pages, ensure_ascii=False))


def articles():
    from kezohar.hebrew import normalize
    pages = json.loads((OUT / 'titles.json').read_text())
    db = sqlite3.connect(str(ROOT / 'data/store/user-library/library.sqlite3'))
    done = {r[0] for r in db.execute("SELECT DISTINCT json_extract(payload,'$.metadata.article') FROM records WHERE file='wikipedia-judaism'")}
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    count = 0
    for title, category in pages.items():
        if title in done:
            continue
        data = api({'action': 'query', 'prop': 'extracts|info', 'explaintext': 1, 'inprop': 'url', 'titles': title, 'redirects': 1})
        time.sleep(0.25)
        page = ((data.get('query') or {}).get('pages') or [{}])[0]
        text, url = page.get('extract') or '', page.get('fullurl') or ''
        section, rows = 'פתיחה', []
        for block in text.split('\n'):
            block = block.strip()
            heading = re.match(r'^=+\s*(.+?)\s*=+$', block)
            if heading:
                section = heading.group(1)
                continue
            if len(block) < 80 or section in ('ראו גם', 'לקריאה נוספת', 'קישורים חיצוניים', 'הערות שוליים'):
                continue
            rows.append((section, block))
        with db:
            for i, (sec, para) in enumerate(rows):
                sid = 'wiki-' + hashlib.sha256(f'{title}|{i}'.encode()).hexdigest()[:16]
                payload = {'source_id': sid, 'work_title': title, 'author': 'ויקיפדיה', 'reference': f'{title} — ויקיפדיה · {sec}',
                           'section': sec, 'text': para, 'normalized_text': normalize(para), 'language': 'he', 'tradition': 'general',
                           'license': 'cc-by-sa-4.0', 'source_url': url, 'version': now[:10], 'ingested_at': now,
                           'book_id': 'Wikipedia_he', 'book_title': 'ויקיפדיה העברית', 'category': 'knowledge',
                           'source_project': 'wikipedia-judaism', 'authority_level': 'secondary-encyclopedia',
                           'verification_status': 'encyclopedia text; attribution required', 'provenance': 'he.wikipedia.org API (plain text)',
                           'metadata': {'article': title, 'category': category, 'paragraph': i, 'knowledge_primary_kind': 'secondary-encyclopedia',
                                        'rag_answers_allowed': True}}
                db.execute('INSERT OR IGNORE INTO records(id,file,payload) VALUES (?,?,?)', (sid, 'wikipedia-judaism', json.dumps(payload, ensure_ascii=False)))
        count += 1
        if count % 200 == 0:
            print(f'{count} articles read', flush=True)
    print('done', count, flush=True)


if __name__ == '__main__':
    {'titles': titles, 'articles': articles}[sys.argv[1]]()
