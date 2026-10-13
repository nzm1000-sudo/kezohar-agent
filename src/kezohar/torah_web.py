"""Bounded, public API research. External text is evidence, never instructions.

Search sends only fixed vocabulary selected locally, never user-written text.
An unreviewed site's access policy cannot be upgraded by robots.txt or HTML.
"""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.parse
from html.parser import HTMLParser
from . import hebrew
from .web_research import ResearchError, USER_AGENT, MAX_PAGE_BYTES, PageParser

SITES = {
    'he.wikisource.org': {'name':'ויקיטקסט','access':'official-api',
        'policy_url':'https://www.mediawiki.org/wiki/API:Etiquette',
        'tradition':'','reliability':'community-transcription','authority':''},
    'www.sefaria.org': {'name':'ספריא','access':'official-api',
        'policy_url':'https://developers.sefaria.org/docs/usage-of-our-name-and-logo',
        'tradition':'','reliability':'text-library','authority':''},
    'halachayomit.co.il': {'name':'הלכה יומית','access':'reference-only',
        'policy_url':'https://halachayomit.co.il/','reason':'automatic access and reuse scope not documented'},
    'yalkutyosef.co.il': {'name':'ילקוט יוסף','access':'reference-only',
        'policy_url':'https://yalkutyosef.co.il/','reason':'web permissions separate from authorized local books'},
    'www.kavhalacha.co.il': {'name':'קו ההלכה הספרדי','access':'reference-only',
        'policy_url':'https://kavhalacha.co.il/','reason':'official identity found; automated reuse needs review'},
    'www.hidabroot.org': {'name':'הידברות','access':'reference-only',
        'policy_url':'https://www.hidabroot.org/','reason':'automated reuse scope needs review'},
    'www.yeshiva.org.il': {'name':'ישיבה','access':'reference-only',
        'policy_url':'https://www.yeshiva.org.il/users/takanon','reason':'reading terms do not establish automated indexing permission'},
    'www.kipa.co.il': {'name':'כיפה','access':'reference-only',
        'policy_url':'https://www.kipa.co.il/','reason':'automated reuse scope needs review'},
}

# These are search hints, not statements of law or equivalent circumstances.
VOCABULARY = ('ברכת המזון','תפילין','אורז','פקאן','מרק','שבת','ראש חודש',
    'יעלה ויבוא','חנוכה','פלטה','בשר','חלב','ציפס','שמן','שניצל','תה',
    'כלי שני','ספירת העומר','תפילת הדרך','מוקצה','נטילת ידים','שולחן ערוך',
    'ילקוט יוסף','עובדיה יוסף','יצחק יוסף','אופיר מלכה','ברכה אחרונה',
    'שש שעות','טבילה','יום טוב','קידוש','הבדלה','דג','מים','לחם','פסח')

def public_queries(question):
    """Closed vocabulary only: no names, numbers, free facts, URLs or history."""
    core=hebrew.normalize(question.split('\n')[0])
    selected=[term for term in VOCABULARY if hebrew.normalize(term) in core]
    if not selected:return []
    if any(term in core for term in ('מברכ','ברכה','ברכת')):selected.append('ברכה')
    if any(term in core for term in ('להמתינ','מחכימ','המתנה')):selected.append('המתנה')
    queries=[' '.join(selected[:7])]
    if 'שמן' in selected and any(t in selected for t in ('ציפס','שניצל')):
        queries+=['טיגון בשמן בשרי','מאכל פרווה בשמן בשרי המתנה']
    elif 'תפילין' in selected and any(x in core for x in ('דבר','לדבר','דיבור')):
        queries.insert(0,'תפילין הפסק דיבור')
    return list(dict.fromkeys(queries))[:3]

def canonical_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443):
        raise ResearchError('HTTPS public source required')
    if p.hostname not in SITES:raise ResearchError('unregistered source')
    return urllib.parse.urlunsplit(('https',p.hostname,p.path or '/',p.query,''))

class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address,timeout):
        super().__init__(host,timeout=timeout,context=ssl.create_default_context())
        self.address=address
    def connect(self):
        # Resolve once, connect to the checked IP, validate TLS for original host.
        raw=socket.create_connection((self.address,443),self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:raw.close();raise

class PublicApiTransport:
    """No proxies/cookies/redirects/JS; DNS rebinding cannot change target IP."""
    def __init__(self,timeout=8,max_requests=18):
        self.timeout=timeout;self.max_requests=max_requests;self.calls=0;self.last={}
    def json(self,url,payload=None,request_budget=None):
        url=canonical_url(url);p=urllib.parse.urlsplit(url)
        if SITES[p.hostname]['access']!='official-api':raise ResearchError('access policy pending')
        if self.calls>=self.max_requests:raise ResearchError('web request limit reached')
        if request_budget:request_budget.check('public API DNS')
        addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
        ips=list(dict.fromkeys(a[4][0] for a in addresses))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ResearchError('non-public DNS target blocked')
        delay=max(0,1-(time.monotonic()-self.last.get(p.hostname,0)))
        if request_budget and delay>=request_budget.remaining():raise ResearchError('rate limit exceeds budget')
        if delay:time.sleep(delay)
        if request_budget:request_budget.check('public API request')
        self.calls+=1;self.last[p.hostname]=time.monotonic()
        timeout=min(self.timeout,request_budget.remaining()) if request_budget else self.timeout
        conn=_PinnedHTTPS(p.hostname,ips[0],timeout)
        try:
            body=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
            conn.request('POST' if body is not None else 'GET',p.path+('?' + p.query if p.query else ''),body,
                {'User-Agent':USER_AGENT,'Accept':'application/json','Content-Type':'application/json; charset=utf-8'})
            response=conn.getresponse()
            if response.status!=200:raise ResearchError('public API HTTP '+str(response.status))
            if response.getheader('Content-Type','').split(';')[0] not in ('application/json','application/problem+json'):
                raise ResearchError('API did not return JSON')
            deadline=time.monotonic()+timeout;chunks=[];size=0
            while size<=MAX_PAGE_BYTES:
                if request_budget:request_budget.check('public API chunk')
                left=deadline-time.monotonic()
                if left<=0:raise ResearchError('API body deadline exceeded')
                if conn.sock:conn.sock.settimeout(min(left,request_budget.remaining()) if request_budget else left)
                chunk=response.read1(min(16384,MAX_PAGE_BYTES+1-size))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
            raw=b''.join(chunks)
            if request_budget:request_budget.check('public API return')
            if len(raw)>MAX_PAGE_BYTES:raise ResearchError('API response too large')
            data=json.loads(raw)
            if not isinstance(data,dict) or data.get('error'):raise ResearchError('API error')
            return data
        finally:conn.close()

class TorahWebSearch:
    def __init__(self,transport=None,cached_urls=None):
        self.transport=transport or PublicApiTransport();self.last_attempts=[];self.last_backend='official-site-apis';self.cached_urls=cached_urls or []
    def search(self,question,limit=5,request_budget=None):
        queries=public_queries(question);urls=list(self.cached_urls[:2]);self.last_attempts=[];batches=[]
        for query in queries[:3]:
            for host in ('www.sefaria.org','he.wikisource.org'):
                if request_budget:request_budget.check('Torah web discovery')
                try:
                    if host=='www.sefaria.org':
                        data=self.transport.json('https://www.sefaria.org/api/search-wrapper',
                            {'query':query,'type':'text','field':'naive_lemmatizer','slop':10,
                             'size':min(limit,8),'source_proj':['ref','heRef','title']},request_budget)
                        found=['https://www.sefaria.org/'+urllib.parse.quote(h['_source']['ref'].replace(' ','_'))
                               for h in data.get('hits',{}).get('hits',[]) if h.get('_source',{}).get('ref')]
                    else:
                        data=self.transport.json('https://he.wikisource.org/w/api.php?'+urllib.parse.urlencode({
                            'action':'query','list':'search','srsearch':query,'srlimit':min(limit,8),
                            'srnamespace':0,'format':'json','maxlag':5}),request_budget=request_budget)
                        found=['https://he.wikisource.org/wiki/'+urllib.parse.quote(h['title'].replace(' ','_'))
                               for h in data.get('query',{}).get('search',[])]
                    batches.append(found)
                    self.last_attempts.append({'backend':host,'query':query,'status':'results','count':len(found)})
                except (OSError,ValueError,ResearchError) as exc:
                    self.last_attempts.append({'backend':host,'query':query,'status':'unavailable','error':str(exc)[:120]})
        # Interleave official providers so a large first batch cannot hide the
        # other site's results. Neither discovery rank nor tradition proves law.
        for position in range(8):
            for batch in batches:
                if position<len(batch):urls.append(batch[position])
        return list(dict.fromkeys(urls))[:min(limit,16)]

class ArticleParser(PageParser):
    """Prefer article/main; never use navigation, comments or JSON-LD as prose."""
    def __init__(self):
        super().__init__();self.stack=[];self.blocks=[];self.links=[];self.structured=[];self.ld=[];self.in_ld=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);parent=self.stack[-1] if self.stack else {'blocked':False,'body':False}
        blocked=parent['blocked'] or tag in ('script','style','nav','footer','header','aside','form','noscript') or bool(
            re.search(r'comment|advert|social|cookie|menu',a.get('class','')+' '+a.get('id',''),re.I))
        body=parent['body'] or tag in ('article','main') or a.get('itemprop') in ('articleBody','acceptedAnswer')
        if tag not in ('br','meta','img','input','hr','link'):self.stack.append({'tag':tag,'blocked':blocked,'body':body})
        if tag=='script' and a.get('type')=='application/ld+json':self.in_ld=True;self.ld=[]
        if tag=='a' and a.get('href') and not blocked:self.links.append(a['href'])
        super().handle_starttag(tag,attrs)
    def handle_endtag(self,tag):
        if tag=='script' and self.in_ld:
            try:self.structured.append(json.loads(''.join(self.ld)))
            except ValueError:pass
            self.in_ld=False
        if any(s['tag']==tag for s in self.stack):
            while self.stack:
                if self.stack.pop()['tag']==tag:break
        super().handle_endtag(tag)
    def handle_data(self,data):
        if self.in_ld:self.ld.append(data)
        if self.stack and self.stack[-1]['body'] and not self.stack[-1]['blocked'] and data.strip():self.blocks.append(data.strip())
        super().handle_data(data)
    def document(self):
        doc=super().document()
        if self.blocks:doc['text']='\n'.join(self.blocks)
        doc.update(updated_at=self.meta.get('article:modified_time',''),links=self.links[:30],
            body_status='article-container' if self.blocks else 'page-fallback',
            author_status='page-declared' if doc['author'] else 'unknown',question='',answer='')
        # Attribution is declared metadata, not independently authenticated.
        nodes=[]
        for entry in self.structured:
            if isinstance(entry,dict):nodes.extend(entry.get('@graph',[entry]))
        for node in nodes:
            if not isinstance(node,dict):continue
            if node.get('@type')=='QAPage':
                q=node.get('mainEntity',{});a=q.get('acceptedAnswer',{}) if isinstance(q,dict) else {}
                if isinstance(a,list):a=a[0] if a else {}
                if not isinstance(a,dict):continue
                doc['question']=q.get('name','');doc['answer']=a.get('text','')
                author=a.get('author',{})
                if isinstance(author,dict) and author.get('name'):
                    doc.update(author=author['name'],author_status='answer-declared; not-authenticated')
        return doc

class TorahWebReader:
    def __init__(self,transport=None):self.transport=transport or PublicApiTransport()
    def read(self,url,request_budget=None):
        url=canonical_url(url);p=urllib.parse.urlsplit(url)
        if SITES[p.hostname]['access']!='official-api':raise ResearchError('site access scope requires review')
        if p.hostname=='he.wikisource.org':
            if not p.path.startswith('/wiki/'):raise ResearchError('not a wiki text locator')
            title=urllib.parse.unquote(p.path[6:]).replace('_',' ')
            data=self.transport.json('https://he.wikisource.org/w/api.php?'+urllib.parse.urlencode({
                'action':'parse','page':title,'prop':'text|revid|displaytitle','format':'json','maxlag':5}),request_budget=request_budget)
            parsed=data.get('parse',{});parser=ArticleParser();parser.feed(parsed.get('text',{}).get('*',''))
            doc=parser.document();doc['title']=parsed.get('title',title)
            doc.update(version='Wikisource revision '+str(parsed.get('revid','unknown')),license='',
                license_status='page-specific-reuse-scope-not-established',locator_status='page-title-url-matched',
                reference=doc['title'],site_name='ויקיטקסט')
        else:
            ref=urllib.parse.unquote(p.path[1:]).replace('_',' ')
            if not ref or ref.startswith(('api/','sheets/')):raise ResearchError('not a text reference')
            data=self.transport.json('https://www.sefaria.org/api/v3/texts/'+urllib.parse.quote(ref,safe='')+
                '?version=hebrew&fill_in_missing_segments=0',request_budget=request_budget)
            versions=[v for v in data.get('versions',[]) if v.get('language') in ('he','hebrew')]
            if len(versions)!=1:raise ResearchError('Hebrew version not uniquely identified')
            v=versions[0];text=v.get('text');pieces=[]
            def flatten(value):
                if isinstance(value,str):pieces.append(value)
                elif isinstance(value,list):
                    for item in value:flatten(item)
            flatten(text);parser=ArticleParser();parser.feed('\n'.join(pieces));doc=parser.document()
            doc.update(title=data.get('heRef') or data.get('ref') or ref,
                reference=data.get('heRef') or data.get('ref') or ref,
                author='',author_status='unknown',version=v.get('versionTitle',''),
                license=v.get('license',''),locator_status='official-api-reference',site_name='ספריא')
        if not doc.get('text') or not doc.get('title'):raise ResearchError('no readable source text')
        doc['source_url']=url
        doc['page_sha256']=hashlib.sha256(doc['text'].encode()).hexdigest()
        return doc

class HalachicSourceAuthority:
    @staticmethod
    def classify(doc):
        # A rabbi's name in a title/footer never makes them the respondent.
        if doc.get('locator_status')=='official-api-reference' and doc.get('version'):
            kind='identified-text-version';level='A-candidate'
        elif doc.get('answer') and doc.get('author_status','').startswith('answer-declared'):
            kind='attributed-answer';level='B-candidate'
        elif doc.get('body_status')=='article-container':kind='explanatory-article';level='C-candidate'
        else:kind='unattributed-content';level='D'
        return {'kind':kind,'level':level,'author_status':doc.get('author_status','unknown'),
            'authority_verified':False,'claim_support':'not-established','halachic_verified':False}

class SimilarHalachicQuestions:
    @staticmethod
    def compare(question,original_question):
        from .question_understanding import analyze
        if not original_question:return {'status':'original-question-unavailable','transfer_allowed':False}
        a,b=analyze(question),analyze(original_question)
        differences=[k for k in set(a['circumstances'])|set(b['circumstances'])
                     if a['circumstances'].get(k)!=b['circumstances'].get(k)]
        same=(a['intent']==b['intent'] or all('יעלה' in q and ('ויבוא' in q or 'ויבא' in q) for q in (question,original_question)))
        return {'same_intent':same,'differing_fields':differences,
            'status':'case-comparison-candidate','transfer_allowed':False,
            'reason':'unknown circumstances and source conditions still require independent verification'}

from .web_research import WebResearchEngine

class HybridHalachicResearch(WebResearchEngine):
    """Existing RAG/verifier with per-request official API discovery and reader."""
    def __init__(self,**kwargs):
        super().__init__(sites=SITES,**kwargs)
        self.allow_local_reuse=False  # Cached URLs always require a new authorized read.
    def research(self,question,limit=5,urls=None,request_budget=None):
        transport=PublicApiTransport()
        index=None
        if self.store_path:
            from .web_metadata import WebMetadataIndex
            from pathlib import Path
            if request_budget:request_budget.check('web metadata index')
            index=WebMetadataIndex(Path(self.store_path).parent/'metadata.sqlite3')
        cached=index.candidates(public_queries(question),limit=2) if index else []
        engine=WebResearchEngine(searcher=TorahWebSearch(transport,cached),fetcher=TorahWebReader(transport),
            sites=self.sites,licenses=self.licenses,grants=self.grants,store_path=self.store_path)
        result=engine.research(question,limit,urls,request_budget)
        if index and (request_budget is None or request_budget.remaining()>0):
            for source in result.get('sources',[]):index.remember(source)
        result['web_policy']={'search_privacy':'closed-topic-vocabulary; no raw conversation',
            'requested_queries':public_queries(question),'max_http_requests':transport.max_requests,
            'requests':transport.calls,'sites':self.sites,'halachic_verified':False}
        result['web_policy']['cached_url_candidates']=len(cached)
        result['opinion_comparison']=HalachicOpinionComparison.compare(question,result.get('sources',[]))
        result['search_status']={'partial':bool(result.get('errors')) or any(
            x.get('status')=='unavailable' for x in result.get('discovery_attempts',[])),
            'errors':result.get('errors',[])+[x for x in result.get('discovery_attempts',[]) if x.get('status')=='unavailable']}
        return result
    def validate_source(self,source,request_budget=None):
        """No cached/source HTML statement can approve its own permissions."""
        from .permissions import permission_for
        try:
            doc=TorahWebReader().read(source['source_url'],request_budget)
            license_id={'Public Domain':'public-domain'}.get(doc.get('license'),doc.get('license',''))
            allowed,permission=permission_for(license_id,self.licenses,self.grants,source['source_url'])
            return (allowed and doc.get('page_sha256')==source.get('metadata',{}).get('page_sha256')
                and doc.get('version')==source.get('version') and license_id==source.get('license')
                and permission==source.get('metadata',{}).get('permission')
                and source.get('metadata',{}).get('source_unit_complete') is True)
        except (OSError,ValueError,ResearchError):return False

class HalachicOpinionComparison:
    @staticmethod
    def compare(question,sources):
        from .halachic_authority import differences
        return {'explicit_attribution_candidates':differences(question,sources),
            'status':'no-automatic-agreement-or-dispute','human_review':'required',
            'halachic_verified':False,'reason':'wording and polarity do not establish same case or a machloket'}
