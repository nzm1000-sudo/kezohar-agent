"""Contemporary Torah sites via Google results (Serper), read only from an owner-approved list.

Modern practical questions (cards on Shabbat, a timer for the air conditioner) are answered by today's poskim on
Q&A sites, not in Sefaria. The search is open (site: operators returned almost nothing), but only pages on the
allowed domains are fetched and read. Page text is data, never instructions.
"""
import hashlib
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from . import config, hebrew

# One place to edit: the owner's approved Torah sites (list of 2026-10-16), domain -> (label, group).
# Groups follow the owner's priority: A Sephardi psak first, B Ashkenazi/Haredi, C Religious-Zionist institutes,
# D Chabad, E text libraries, F English. The label keeps each posek's identity separate in the answer.
SITES = {
    'yalkutyosef.co.il': ('ילקוט יוסף – הרב יצחק יוסף', 'A'),
    'halachayomit.co.il': ('הלכה יומית – לפי פסקי הרב עובדיה יוסף', 'A'),
    'kavhalacha.co.il': ('קו ההלכה הספרדי', 'A'),
    'doresh-tzion.co.il': ('דורש ציון – הרב בן ציון מוצפי', 'A'),
    'hl5047.co.il': ('הלכה למעשה – הרב אופיר מלכא', 'A'),
    'ykr.org.il': ('ישיבת כסא רחמים', 'A'),
    'harav.org': ('אתר הרב מרדכי אליהו', 'A'),
    'orlezion.org.il': ('ישיבת אור לציון', 'A'),
    'net-sah.org': ('נצח ישראל – הרב רצון ערוסי', 'A'),
    'dailyhalacha.com': ('Daily Halacha – הרב אלי מנסור', 'A'),
    'din.org.il': ('דין – בית הוראה', 'B'),
    'dirshu.co.il': ('דרשו', 'B'),
    'moreshesashkenaz.org': ('מכון מורשת אשכנז', 'B'),
    'yeshiva.org.il': ('אתר ישיבה', 'C'),
    'ph.yhb.org.il': ('פניני הלכה – הרב אליעזר מלמד', 'C'),
    'toraland.org.il': ('מכון התורה והארץ', 'C'),
    'eretzhemdah.org': ('ארץ חמדה', 'C'),
    'etzion.org.il': ('ישיבת הר עציון', 'C'),
    'meirtv.com': ('ערוץ מאיר – מכון מאיר', 'C'),
    'kosharot.co.il': ('כושרות', 'C'),
    'puah.org.il': ('מכון פוע"ה', 'C'),
    'yoatzot.org': ('יועצות הלכה – נשמת', 'C'),
    'zomet.org.il': ('מכון צומת', 'C'),
    'keter.org.il': ('מכון כת"ר', 'C'),
    'templeinstitute.org': ('מכון המקדש', 'C'),
    'machon-halacha.co.il': ('מכון הלכה חב"ד', 'D'),
    'chabad.org': ('חב"ד – Chabad.org', 'D'),
    'asktherav.com': ('AskTheRav', 'D'),
    'chabadlibrary.org': ('ספריית חב"ד', 'D'),
    'chabadpedia.co.il': ('חב"דפדיה', 'D'),
    'mikvah.org': ('Mikvah.org', 'D'),
    'sefaria.org': ('ספריא', 'E'),
    'mechon-mamre.org': ('מכון ממרא', 'E'),
    'alhatorah.org': ('על התורה', 'E'),
    'hebrewbooks.org': ('היברו בוקס', 'E'),
    'toratemetfreeware.com': ('תורת אמת', 'E'),
    'otzar.org': ('אוצר החכמה', 'E'),
    'responsa.co.il': ('פרויקט השו"ת – בר אילן', 'E'),
    'he.wikisource.org': ('אוצר הספרים היהודי השיתופי', 'E'),
    'daat.ac.il': ('דעת – לימודי יהדות ורוח', 'E'),
    'daf-yomi.com': ('פורטל הדף היומי', 'E'),
    'opensiddur.org': ('Open Siddur', 'E'),
    'yutorah.org': ('YUTorah', 'F'),
    'torahweb.org': ('TorahWeb', 'F'),
    'halachipedia.com': ('Halachipedia', 'F'),
    'torah.org': ('Torah.org', 'F'),
    'outorah.org': ('OU Torah', 'F'),
    'ohr.edu': ('Ohr Somayach', 'F'),
    'practicalhalacha.com': ('Practical Halacha', 'F'),
    'star-k.org': ('STAR-K', 'F'),
    'oukosher.org': ('OU Kosher', 'F'),
    'ok.org': ('OK Kosher', 'F'),
    'kof-k.org': ('KOF-K Kosher', 'F'),
    'torahanytime.com': ('TorahAnytime', 'F'),
    'kolhalashon.com': ('קול הלשון', 'F'),
    'rabbisacks.org': ('Rabbi Sacks', 'F'),
    'breslov.com': ('Breslov.com', 'F'),
}
ALLOWED = tuple(SITES)


def site_of(url):
    host = urllib.parse.urlsplit(url).hostname or ''
    return next((d for d in SITES if host == d or host.endswith('.' + d)), None)


def allowed(url):
    return urllib.parse.urlsplit(url).scheme == 'https' and site_of(url) is not None


class _Text(HTMLParser):
    SKIP = {'script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'noscript', 'svg'}
    BLOCK = {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'div', 'br', 'td', 'blockquote'}

    def __init__(self):
        super().__init__()
        self.depth, self.parts, self.title, self._in_title = 0, [], '', False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        if tag == 'title':
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.depth:
            self.parts.append(data)


CACHE_DAYS = 30
BRAVE_MONTHLY_CAP = 900  # free credit is 1,000/month; keep a margin


def _cache():
    import sqlite3
    from pathlib import Path
    path = Path(config.get('TORAH_SITES_CACHE', 'data/store/torah-sites-cache.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=5)
    db.execute('CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, fetched REAL, title TEXT, paragraphs TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS searches (query TEXT PRIMARY KEY, fetched REAL, results TEXT)')
    return db


def _clean_title(title):
    # Site chrome glued to titles ("כלי נגישותהגדל טקסט...", "accessibility").
    title = re.split(r'כלי נגישות|accessibility', title or '', maxsplit=1, flags=re.I)[0]
    return re.sub(r'\s+', ' ', title).strip(' -|·')


def _fetch(url, timeout=8):
    """Page text, from the local store when read in the last CACHE_DAYS (no repeated downloads)."""
    import time
    db = _cache()
    row = db.execute('SELECT fetched, title, paragraphs FROM pages WHERE url=?', (url,)).fetchone()
    if row and time.time() - row[0] < CACHE_DAYS * 86400:
        return row[1], json.loads(row[2])
    try:
        page = _download(url, timeout)
    except Exception:
        page = None
    if not page or sum(len(p) for p in page[1]) < 300:
        page = _jina(url) or page  # pages built by JavaScript come back empty from a plain download
    if page:
        with db:
            db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?)', (url, time.time(), page[0], json.dumps(page[1], ensure_ascii=False)))
    return page


def _jina(url, timeout=20):
    """Clean page text via Jina Reader (free key); only for allowed sites."""
    key = config.get('JINA_API_KEY', '')
    if not key or not allowed(url):
        return None
    req = urllib.request.Request('https://r.jina.ai/' + url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r).get('data', {})
    except Exception:
        return None
    from .web_answer import clean_web_text
    return _clean_title(data.get('title', '')), [clean_web_text(re.sub(r'\s+', ' ', p)) for p in (data.get('content') or '').split('\n')]


def _download(url, timeout=8):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (KezoharAgent; Torah study)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if not allowed(r.geturl()) or 'html' not in (r.headers.get('Content-Type') or ''):
            return None
        raw = r.read(2_000_001)
    if len(raw) > 2_000_000:
        return None
    parser = _Text()
    parser.feed(raw.decode('utf-8', 'replace'))
    return _clean_title(parser.title), [re.sub(r'\s+', ' ', p).strip() for p in ''.join(parser.parts).split('\n')]


def search(question, limit=4, keep=3):
    """Paragraph sources from allowed Torah sites, most relevant first. Empty when no key or nothing allowed."""
    brave = config.get('BRAVE_API_KEY', '')
    serper = config.get('SERPER_API_KEY', '') if config.get('TORAH_SITES', '0') == '1' else ''
    # Brave first (owner, 2026-10-16: $5 free credit monthly = 1,000 searches). Serper's quota is one-time: opt-in only.
    if not brave and not serper:
        return []
    import time
    db = _cache()
    query = re.sub(r'\s+', ' ', question).strip()
    row = db.execute('SELECT fetched, results FROM searches WHERE query=?', (query,)).fetchone()
    if row and time.time() - row[0] < CACHE_DAYS * 86400:
        results = json.loads(row[1])  # the same question does not spend another search
    else:
        if brave:
            month = time.strftime('%Y-%m')
            used = db.execute('SELECT COUNT(*) FROM searches WHERE strftime("%Y-%m", fetched, "unixepoch")=?', (month,)).fetchone()[0]
            if used >= BRAVE_MONTHLY_CAP:
                return []  # stay inside the free monthly credit; never billed
            req = urllib.request.Request('https://api.search.brave.com/res/v1/web/search?' + urllib.parse.urlencode(
                {'q': question, 'count': 20}),
                headers={'X-Subscription-Token': brave, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as r:
                results = [{'link': o.get('url')} for o in json.load(r).get('web', {}).get('results', [])]
        else:
            req = urllib.request.Request('https://google.serper.dev/search', method='POST',
                                         data=json.dumps({'q': question, 'gl': 'il', 'hl': 'iw', 'num': 10}).encode(),
                                         headers={'X-API-KEY': serper, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as r:
                results = json.load(r).get('organic', [])
        with db:
            db.execute('INSERT OR REPLACE INTO searches VALUES (?,?,?)', (query, time.time(), json.dumps(results, ensure_ascii=False)))
    # Google's order within the owner's priority groups: Sephardi psak first.
    media = re.compile(r'/(?:audio|video|shiurim|player|wp-content/uploads)/|\.(?:pdf|mp3|mp4)(?:$|\?)', re.I)
    urls = [o['link'] for o in results if isinstance(o.get('link'), str) and allowed(o['link'])
            and not media.search(o['link'])]  # audio/video/PDF pages have no readable answer text
    urls = sorted(urls, key=lambda u: SITES[site_of(u)][1])[:limit]
    words = [w for w in hebrew.normalize(question).split() if len(w) > 2]
    sources = []
    for url in urls:
        try:
            page = _fetch(url)
        except Exception:
            continue
        if not page:
            continue
        title, paragraphs = page
        # Menus and tables of contents ("א • ב • ג") match every keyword but answer nothing.
        paragraphs = [p for p in paragraphs if 40 <= len(p) <= 2000 and p.count('•') + p.count('|') < 3]
        if not paragraphs:
            continue
        # The best-matching paragraph is usually the asker's question; the rabbi's answer follows it.
        best = max(range(len(paragraphs)), key=lambda i: (sum(w in hebrew.normalize(paragraphs[i]) for w in words),
                                                         min(len(paragraphs[i]), 400)))
        passage = ''
        for p in paragraphs[best:best + 6]:
            if len(passage) + len(p) > 1800:
                break
            passage += ('\n' if passage else '') + p
        ranked = [passage][:keep]
        site = SITES[site_of(url)][0]
        for i, text in enumerate(ranked):
            sources.append({'source_id': 'site-' + hashlib.sha256((url + str(i)).encode()).hexdigest()[:16],
                            'reference': (title or site) + ' — ' + site, 'text': text, 'source_url': url,
                            'work_title': title or site, 'attribution': site,
                            'metadata': {'knowledge_primary_kind': 'contemporary-torah-site', 'rag_answers_allowed': True}})
    return sources
