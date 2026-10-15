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

# One place to edit: the owner's approved Torah sites.
ALLOWED = ('din.org.il', 'yeshiva.org.il', 'hidabroot.org', 'halachayomit.co.il', 'ph.yhb.org.il', 'yhb.org.il',
           'daat.ac.il', 'moreshet.co.il', 'kipa.co.il', 'chabad.org.il', 'meirtv.com', 'torahbox.com',
           'beinenu.com', 'shituf.co.il', 'dirshu.co.il', 'halachabrura.co.il')


def allowed(url):
    host = urllib.parse.urlsplit(url).hostname or ''
    return urllib.parse.urlsplit(url).scheme == 'https' and any(host == d or host.endswith('.' + d) for d in ALLOWED)


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


def _fetch(url, timeout=8):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (KezoharAgent; Torah study)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if not allowed(r.geturl()) or 'html' not in (r.headers.get('Content-Type') or ''):
            return None
        raw = r.read(2_000_001)
    if len(raw) > 2_000_000:
        return None
    parser = _Text()
    parser.feed(raw.decode('utf-8', 'replace'))
    return parser.title.strip(), [re.sub(r'\s+', ' ', p).strip() for p in ''.join(parser.parts).split('\n')]


def search(question, limit=3, keep=3):
    """Paragraph sources from allowed Torah sites, most relevant first. Empty when no key or nothing allowed."""
    key = config.get('SERPER_API_KEY', '')
    if not key:
        return []
    req = urllib.request.Request('https://google.serper.dev/search', method='POST',
                                 data=json.dumps({'q': question, 'gl': 'il', 'hl': 'iw', 'num': 10}).encode(),
                                 headers={'X-API-KEY': key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        results = json.load(r).get('organic', [])
    urls = [o['link'] for o in results if isinstance(o.get('link'), str) and allowed(o['link'])][:limit]
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
        paragraphs = [p for p in paragraphs if 40 <= len(p) <= 2000]
        if not paragraphs:
            continue
        # The best-matching paragraph is usually the asker's question; the rabbi's answer follows it.
        best = max(range(len(paragraphs)), key=lambda i: sum(w in hebrew.normalize(paragraphs[i]) for w in words))
        passage = ''
        for p in paragraphs[best:best + 6]:
            if len(passage) + len(p) > 1800:
                break
            passage += ('\n' if passage else '') + p
        ranked = [passage][:keep]
        site = urllib.parse.urlsplit(url).hostname
        for i, text in enumerate(ranked):
            sources.append({'source_id': 'site-' + hashlib.sha256((url + str(i)).encode()).hexdigest()[:16],
                            'reference': (title or site) + ' — ' + site, 'text': text, 'source_url': url,
                            'work_title': title or site, 'attribution': site,
                            'metadata': {'knowledge_primary_kind': 'contemporary-torah-site', 'rag_answers_allowed': True}})
    return sources
