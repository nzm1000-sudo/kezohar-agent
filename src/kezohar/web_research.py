"""Free web RAG: discovery -> allowed public pages -> evidence -> guarded answer.

No site reputation is treated as proof of a claim. Unknown rights: transient
short excerpts only. Full-text persistence requires explicit scoped permission.
"""
from . import evidence
import argparse
import fcntl
import html
import ipaddress
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from . import citations, hebrew, llm
from .hybrid import HybridSearch
from .ingest import load_licenses
from .models import Source, stable_id, utcnow_iso
from .permissions import permission_for, rag_eligible
from .ranking import topic_tokens, topic_overlap, STOP

USER_AGENT = 'KezoharResearch/1.0'
MAX_PAGE_BYTES = 2 * 1024 * 1024
DEFAULT_SITES = {
    'halachayomit.co.il': {'tradition':'sephardi', 'reliability':'editorial-halacha',
                         'authority':'פסקי הרב עובדיה יוסף, כפי שמובאים באתר',
                         'authority_evidence':'https://halachayomit.co.il/'},
    'yalkutyosef.co.il': {'tradition':'sephardi', 'reliability':'author-site',
                        'authority':'אתר ילקוט יוסף — הרב יצחק יוסף',
                        'authority_evidence':'https://yalkutyosef.co.il/אודות/'},
    'he.wikisource.org': {'tradition':'', 'reliability':'community-transcription', 'authority':''},
    'www.sefaria.org': {'tradition':'', 'reliability':'text-library', 'authority':''},
    'he.chabad.org': {'tradition':'ashkenazi', 'reliability':'editorial-halacha', 'authority':'מנהג חב״ד'},
}

class ResearchError(Exception):
    pass

def public_url(url, allowed_hosts=None):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http','https') or not host or parts.username or parts.password or parts.port not in (None,80,443):
        raise ResearchError('invalid public URL')
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ResearchError('domain outside configured sources')
    try:
        addresses = socket.getaddrinfo(host, parts.port or (443 if parts.scheme=='https' else 80), type=socket.SOCK_STREAM)
    except OSError:
        raise ResearchError('DNS unavailable')
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ResearchError('non-public address blocked')
    return urllib.parse.urlunsplit((parts.scheme,parts.netloc,parts.path or '/',parts.query,''))

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts, check=None): self.hosts=hosts;self.check=check
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl,self.hosts)
        if self.check and not self.check(req.full_url, newurl):
            raise ResearchError("redirect robots policy not established")
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class PublicFetcher:
    def __init__(self, hosts, timeout=8):
        self.hosts=set(hosts);self.timeout=timeout;self.robots={};self.last={}
        self.opener=urllib.request.build_opener(SafeRedirect(self.hosts,self._redirect_allowed))
    def _redirect_allowed(self, old, new):
        origin = urllib.parse.urlsplit(new)
        origin = origin.scheme+'://'+origin.netloc
        if urllib.parse.urlsplit(old).path=='/robots.txt':
            return urllib.parse.urlsplit(new).path=='/robots.txt' and urllib.parse.urlsplit(old).netloc==urllib.parse.urlsplit(new).netloc
        robots = self.robots.get(origin)
        return robots is not None and robots.can_fetch(USER_AGENT,new)
    def _read(self,url):
        public_url(url,self.hosts)
        req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'text/html,text/plain'})
        with self.opener.open(req,timeout=self.timeout) as response:
            final=public_url(response.geturl(),self.hosts)
            kind=response.headers.get_content_type()
            if kind not in ('text/html','text/plain','application/xhtml+xml'):
                raise ResearchError('unsupported page type')
            raw=response.read(MAX_PAGE_BYTES+1)
            if len(raw)>MAX_PAGE_BYTES:raise ResearchError('page too large')
            return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'),final
    def __call__(self,url):
        url=public_url(url,self.hosts);parts=urllib.parse.urlsplit(url)
        origin=parts.scheme+'://'+parts.netloc
        if origin not in self.robots:
            parser=urllib.robotparser.RobotFileParser()
            try:
                text,_=self._read(origin+'/robots.txt');parser.parse(text.splitlines())
            except urllib.error.HTTPError as exc:
                if exc.code==404:parser.parse([])
                else:raise ResearchError('robots unavailable')
            except (OSError,ResearchError):raise ResearchError('robots unavailable')
            self.robots[origin]=parser
        robots=self.robots[origin]
        if not robots.can_fetch(USER_AGENT,url):raise ResearchError('robots disallow page')
        delay=max(1,robots.crawl_delay(USER_AGENT) or 0)
        if delay>10:raise ResearchError('crawl delay exceeds research budget')
        remaining=delay-(time.monotonic()-self.last.get(origin,0))
        if remaining>0:time.sleep(remaining)
        self.last[origin]=time.monotonic()
        page,final=self._read(url)
        if final!=url and not robots.can_fetch(USER_AGENT,final):
            raise ResearchError('robots disallow redirect target')
        return page,final

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip=0;self.title_depth=0;self.in_h1=0;self.parts=[];self.title=[];self.h1=[];self.meta={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style','nav','footer','header','noscript'):self.skip+=1
        if tag=='title':self.title_depth+=1
        if tag=='h1':self.in_h1+=1
        if tag=='meta':
            key=attrs.get('name') or attrs.get('property') or ''
            self.meta[key.lower()]=attrs.get('content','')
        if tag in ('p','div','br','li','h1','h2','h3','article','section'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','nav','footer','header','noscript'):self.skip=max(0,self.skip-1)
        if tag=='title':self.title_depth=max(0,self.title_depth-1)
        if tag=='h1':self.in_h1=max(0,self.in_h1-1)
        if tag in ('p','div','li','article','section'):self.parts.append('\n')
    def handle_data(self,data):
        if self.title_depth:self.title.append(data)
        if self.in_h1:self.h1.append(data)
        if not self.skip and not self.title_depth:self.parts.append(data)
    def document(self):
        text='\n'.join(re.sub(r'\s+',' ',p).strip() for p in ''.join(self.parts).splitlines() if p.strip())
        title=self.meta.get('og:title') or ''.join(self.title).strip() or ''.join(self.h1).strip()
        return {'title':title,'text':text,'author':self.meta.get('author') or self.meta.get('article:author',''),
                'published_at':self.meta.get('article:published_time','')}

class LinkParser(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and 'result__a' in a.get('class',''):
            url=a.get('href','');p=urllib.parse.urlsplit(url);query=urllib.parse.parse_qs(p.query)
            self.urls.append(query.get('uddg',[url])[0])

class FreeSearch:
    """Configured SearxNG JSON endpoint, or public DuckDuckGo HTML (best effort)."""
    def __init__(self,searx_url=None,timeout=8):
        self.searx_url=searx_url;self.timeout=timeout;self.last_backend="";self.last_attempts=[]
    def search(self,query,limit=5):
        self.last_attempts=[{'backend':'searxng','status':'configured' if self.searx_url else 'not-configured'}]
        if self.searx_url:
            self.last_backend='searxng'
            url=self.searx_url.rstrip('/')+'/search?'+urllib.parse.urlencode({'q':query,'format':'json'})
            req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
            with urllib.request.urlopen(req,timeout=self.timeout) as response:
                data=json.loads(response.read(MAX_PAGE_BYTES+1))
            return [r['url'] for r in data.get('results',[]) if r.get('url')][:limit]
        try:
            fetch=PublicFetcher({'html.duckduckgo.com'},timeout=self.timeout)
            page,_=fetch._read('https://html.duckduckgo.com/html/?'+urllib.parse.urlencode({'q':query}))
            parser=LinkParser();parser.feed(page)
            if parser.urls:
                self.last_attempts.append({'backend':'duckduckgo-html','status':'links-found','count':len(parser.urls)})
                self.last_backend='duckduckgo-html'
                return parser.urls[:limit]
            self.last_attempts.append({'backend':'duckduckgo-html','status':'challenge-page' if re.search(r'anomaly|captcha|challenge',page,re.I) else 'no-parseable-links'})
        except (OSError, ResearchError) as exc:
            self.last_attempts.append({'backend':'duckduckgo-html','status':'error','error':type(exc).__name__})
        # Documented public MediaWiki search API, no key/account/payment.
        topic = query.split(' הלכה site:',1)[0]
        stop = {'מה','מתי','האם','איך','על','של','עם','מותר','מברכים','ברכת','הלכה'}
        terms = [t for t in re.findall(r'[א-תA-Za-z]+',hebrew.strip_niqqud(topic))
                 if hebrew.normalize(t) not in STOP and len(t)>1]
        if not terms:
            return []
        url='https://he.wikisource.org/w/api.php?'+urllib.parse.urlencode({
            'action':'query','list':'search','srsearch':' OR '.join(terms[:6]),
            'srlimit':max(1,min(limit,20)),'format':'json'})
        public_url(url, {'he.wikisource.org'})
        opener=urllib.request.build_opener(SafeRedirect({'he.wikisource.org'}))
        with opener.open(urllib.request.Request(url,headers={'User-Agent':USER_AGENT}),timeout=self.timeout) as response:
            raw=response.read(MAX_PAGE_BYTES+1)
            if len(raw)>MAX_PAGE_BYTES:raise ResearchError('search response too large')
            data=json.loads(raw)
        if data.get('error'):raise ResearchError('wiki search unavailable')
        self.last_backend='wikisource-api-fallback'
        self.last_attempts.append({'backend':'wikisource-api-fallback','status':'results','count':len(data.get('query',{}).get('search',[]))})
        return ['https://he.wikisource.org/wiki/'+urllib.parse.quote(r['title'].replace(' ','_'))
                for r in data.get('query',{}).get('search',[])][:limit]

def rank_sources(sources):
    """Independent axes remain visible; relevance eligibility precedes tradition."""
    return sorted(sources,key=lambda s:(s.get('tradition')!='sephardi',
                 s.get('metadata',{}).get('content_kind')!='ruling-candidate',-s.get('score',0)))

def passages(text,question):
    candidates=[]
    topic = topic_tokens(question)
    if not topic:
        return []
    for part in re.split(r'\n+|(?<=[.!?׃])\s+',text):
        overlap=topic_overlap(part,question)
        relevant=overlap>=min(2,len(topic))
        if relevant and len(part)>15:
            candidates.append((overlap,part.strip()))
    return [p for _,p in sorted(candidates,key=lambda x:-x[0])]


def short_excerpt(passage, question, word_limit=25):
    """Keep a contiguous window around a topical word, preserving exact wording."""
    words = passage.split()
    topic = topic_tokens(question)
    matches=[i for i,w in enumerate(words) if any(citations._tok_match(t,s) for t in topic for s in hebrew.tokens(w))]
    center = matches[0] if matches else 0
    start=max(0,min(center-5,len(words)-word_limit))
    return ' '.join(words[start:start+word_limit])

def compare(sources):
    """Only flag possible differences; polarity alone cannot establish machloket."""
    candidates=[]
    for i,a in enumerate(sources):
        for b in sources[i+1:]:
            at=hebrew.normalize(a['text']);bt=hebrew.normalize(b['text'])
            if ('אסור' in at and 'מותר' in bt) or ('מותר' in at and 'אסור' in bt):
                candidates.append({'sources':[a['source_id'],b['source_id']],
                                   'status':'possible-difference-needs-context',
                                   'explanation':'נמצאו לשונות היתר ואיסור; אין בכך לבדו הוכחה למחלוקת באותו מקרה'})
    return candidates

def save_verified(source, path):
    """Atomic upsert of an authorized exact excerpt, serialized across writers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = {}
        if path.exists():
            with path.open(encoding='utf-8') as fh:
                for line in fh:
                    if line.strip():
                        row=json.loads(line);rows[row['source_id']]=row
        rows[source.source_id]=source.to_dict()
        temporary=path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as fh:
            for row in rows.values():
                fh.write(json.dumps(row,ensure_ascii=False)+'\n')
            fh.flush();os.fsync(fh.fileno())
        os.replace(str(temporary),str(path))

class WebResearchEngine:
    def __init__(self,searcher=None,fetcher=None,sites=None,licenses=None,grants=None,store_path=None):
        self.sites=DEFAULT_SITES if sites is None else sites
        self.searcher=searcher or FreeSearch(os.environ.get('SEARXNG_URL'))
        self.fetcher=fetcher or PublicFetcher(self.sites)
        self.licenses=load_licenses() if licenses is None else licenses
        self.grants=grants or {};self.store_path=store_path
        if store_path and Path(__file__).resolve().parents[2] not in Path(store_path).resolve().parents:
            raise ValueError('web store must be inside agent project')
    def research(self,question,limit=5,urls=None):
        limit=max(1,min(int(limit),8)); errors=[];sources=[];seen=set();rejected=[]
        if not question.strip() or len(question)>2000:raise ValueError('invalid question')
        try:
            urls=urls if urls is not None else self.searcher.search(question+' הלכה '+ ' OR '.join('site:'+h for h in self.sites),limit*2)
        except Exception as exc:
            return {'sources':[],'errors':[{'stage':'search','error':type(exc).__name__}], 'comparisons':[],
                    'answer':'אין לי מקור לכך. חיפוש האינטרנט אינו זמין.','mode':'web-sources-only'}
        for url in urls[:limit*2]:
            if len(sources)>=limit:break
            host=urllib.parse.urlsplit(url).hostname
            if host not in self.sites or url in seen:continue
            seen.add(url)
            try:
                page,final=self.fetcher(url)
                if urllib.parse.urlsplit(final).hostname not in self.sites:raise ResearchError('redirect outside source registry')
                if final in seen and final!=url:continue
                seen.add(final)
                parser=PageParser();parser.feed(page);doc=parser.document()
                from .source_quality import classify, exclusion_reason, web_locator_issue
                reason=web_locator_issue(doc['title'],final) or exclusion_reason(question, {'work_title':doc['title'], 'source_url':final,
                                                   'text':doc['text']}, web=True)
                if reason:
                    rejected.append({'url':final,'title':doc['title'],'reason':reason})
                    continue
                relevant=passages(doc['text'],question)
                if not relevant or not doc['title']:continue
                profile=self.sites[urllib.parse.urlsplit(final).hostname]
                allowed,permission=permission_for(profile.get('license',''),self.licenses,self.grants,final)
                # Rights-unknown sites contribute a short transient excerpt, never the full page.
                snippet=short_excerpt(relevant[0],question) if not allowed else relevant[0][:1500]
                kind='ruling-candidate' if re.search(r'הלכה|פסק|שו״ת|שו"ת|שאלות ותשובות',doc['title']+' '+snippet) else 'general-article'
                source=Source(source_id=stable_id('web',final,snippet),work_title=doc['title'],reference=doc['title']+' — '+final,
                    text=snippet,normalized_text=hebrew.normalize(snippet),author=doc['author'],
                    source_url=final,license=profile.get('license','unknown'),tradition=profile.get('tradition',''),
                    source_project='verified-web',verification_status='excerpt-verified',ingested_at=utcnow_iso(),
                    authority_level=profile.get('authority',''),attribution=doc['title']+' · '+final,
                    license_url=self.licenses.get(profile.get('license',''),{}).get('url',''),
                    metadata={'content_kind':kind,'source_reliability':profile.get('reliability','unknown'),
                              'authority_evidence':profile.get('authority_evidence',''),'author_status':'page-declared' if doc['author'] else 'unknown',
                              'evidence_support':'exact-excerpt-only','persistence_allowed':allowed,'permission':permission,
                              'published_at':doc['published_at'],'references_in_page':citations.extract_refs(snippet),
                              'page_sha256':__import__('hashlib').sha256(doc['text'].encode()).hexdigest(),
                              'rights_mode':'licensed' if allowed else 'transient-25-word-excerpt'})
                source.metadata.update(classify(source.to_dict()))
                source.metadata['locator_granularity']='page-title-and-url; unit locator not independently established'
                source.metadata['locator_status']='page-title-url-matched' if urllib.parse.urlsplit(final).hostname=='he.wikisource.org' else 'fetched-page-only'
                # Full-text store still contains only relevant exact passages, not boilerplate.
                if allowed and self.store_path:
                    save_verified(source,self.store_path)
                sources.append(source)
            except Exception as exc:
                errors.append({'url':url,'error':type(exc).__name__})
        results=rank_sources(HybridSearch(sources).search(question,top_k=limit)) if sources else []
        return {'sources':results,'errors':errors,'rejected_sources':rejected,'comparisons':compare(results),
                'answer':evidence.INSUFFICIENT if evidence.shared_oil_waiting(question) else self.extractive_answer(results),'mode':'web-evidence','verdict':'insufficient_context' if evidence.shared_oil_waiting(question) else 'exact-extract-only','discovery_backend':getattr(self.searcher,'last_backend','custom'),'discovery_attempts':getattr(self.searcher,'last_attempts',[]),'verification':{'support':'exact-excerpts','psak':'not-inferred'}}
    def answer(self, question, base_url, model, limit=5, urls=None, timeout=15, local_sources=None, answer_model=None, source_verifier=None):
        result = self.research(question, limit=limit, urls=urls)
        result.update(human_review='required', halachic_verified=False)
        local_sources = [s for s in (local_sources or []) if rag_eligible(s)]
        if local_sources:
            from .agent import order_sources
            unique = {s['source_id']:s for s in list(local_sources)+result['sources']}
            result['sources'] = order_sources(list(unique.values()),question)[:limit]
            result['answer'] = self.extractive_answer(result['sources'])
            result['comparisons'] = compare(result['sources'])
        from .verification import ExtractiveSourceVerifier
        verifier = source_verifier if source_verifier is not None else ExtractiveSourceVerifier()
        eligible = verifier.eligible_sources(question, result['sources'])
        if evidence.shared_oil_waiting(question):
            result.update(answer=evidence.INSUFFICIENT, verdict='insufficient_context', mode='web-evidence')
        if not eligible:
            result.update(answer=evidence.INSUFFICIENT if evidence.shared_oil_waiting(question) else 'אין במקורות שנמצאו ראיה מספקת למקרה שנשאל. נדרשים מקור מתאים ובדיקת ההקשר.',
                          verdict='insufficient_context',
                          verification={'verdict':'insufficient_context','support':'no eligible source; generation blocked'})
            return result
        result['sources'] = eligible
        from .answer_models import ConfiguredAnswerModel
        generator = answer_model if answer_model is not None else ConfiguredAnswerModel(base_url, model)
        try:
            generated = generator.generate(question, result['sources'], timeout=timeout)['answer']
            verification = verifier.verify(question, generated, result['sources'])
            result['verification'] = verification
            if verification['verdict']=='ok':
                result.update(answer=verification.get('rendered_answer',generated), mode='web-llm-verified', verdict=verification.get('support','exact-extract-only'))
            elif verification['verdict']=='no_source':
                result.update(answer=verification.get('rendered_answer','אין לי מקור לכך.'), mode='web-llm-guarded', verdict='no_source')
            else:
                result['mode']='web-llm-guarded'
                result['verdict']=verification['verdict']
        except llm.LLMUnavailable:
            result['mode']='web-sources-only'
        return result

    @staticmethod
    def extractive_answer(sources):
        if not sources:return 'אין לי מקור לכך.'
        return 'מקורות לבדיקה (הציטוטים אינם פסיקה עצמאית):\n'+'\n'.join(
            '״{}״ ({})'.format(s['text'],s['reference']) for s in sources[:3])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('question');parser.add_argument('--url',action='append');parser.add_argument('--store')
    args=parser.parse_args();print(json.dumps(WebResearchEngine(store_path=args.store).research(args.question,urls=args.url),ensure_ascii=False,indent=2))
