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

def public_url(url, allowed_hosts=None, request_budget=None):
    if request_budget:request_budget.check('URL/DNS validation')
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
    if request_budget:request_budget.check('DNS return')
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ResearchError('non-public address blocked')
    return urllib.parse.urlunsplit((parts.scheme,parts.netloc,parts.path or '/',parts.query,''))

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts, check=None, request_budget=None):
        self.hosts=hosts;self.check=check;self.request_budget=request_budget
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl,self.hosts,self.request_budget)
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
    def _read(self,url,request_budget=None):
        public_url(url,self.hosts,request_budget)
        req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'text/html,text/plain'})
        opener=(urllib.request.build_opener(SafeRedirect(self.hosts,self._redirect_allowed,request_budget))
                if request_budget else self.opener)
        if request_budget:request_budget.check('page request')
        with opener.open(req,timeout=min(self.timeout,request_budget.remaining()) if request_budget else self.timeout) as response:
            final=public_url(response.geturl(),self.hosts,request_budget)
            kind=response.headers.get_content_type()
            if kind not in ('text/html','text/plain','application/xhtml+xml'):
                raise ResearchError('unsupported page type')
            raw=response.read(MAX_PAGE_BYTES+1)
            if request_budget:request_budget.check('page read return')
            if len(raw)>MAX_PAGE_BYTES:raise ResearchError('page too large')
            return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'),final
    def __call__(self,url,request_budget=None):
        url=public_url(url,self.hosts,request_budget);parts=urllib.parse.urlsplit(url)
        origin=parts.scheme+'://'+parts.netloc
        if origin not in self.robots:
            parser=urllib.robotparser.RobotFileParser()
            try:
                text,_=self._read(origin+'/robots.txt',request_budget);parser.parse(text.splitlines())
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
        if remaining>0:
            if request_budget and remaining>=request_budget.remaining():
                request_budget.reason='crawl delay exceeds request deadline'
                from .request_budget import BudgetExceeded
                raise BudgetExceeded(request_budget.reason)
            time.sleep(remaining)
        if request_budget:request_budget.check('page fetch after crawl delay')
        self.last[origin]=time.monotonic()
        page,final=self._read(url,request_budget)
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
    def search(self,query,limit=5,request_budget=None):
        if request_budget:request_budget.check('web search')
        self.last_attempts=[{'backend':'searxng','status':'configured' if self.searx_url else 'not-configured'}]
        if self.searx_url:
            self.last_backend='searxng'
            url=self.searx_url.rstrip('/')+'/search?'+urllib.parse.urlencode({'q':query,'format':'json'})
            req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
            if request_budget:request_budget.check('Searx request')
            with urllib.request.urlopen(req,timeout=min(self.timeout,request_budget.remaining()) if request_budget else self.timeout) as response:
                data=json.loads(response.read(MAX_PAGE_BYTES+1))
            if request_budget:request_budget.check('Searx return')
            return [r['url'] for r in data.get('results',[]) if r.get('url')][:limit]
        try:
            fetch=PublicFetcher({'html.duckduckgo.com'},timeout=self.timeout)
            page,_=fetch._read('https://html.duckduckgo.com/html/?'+urllib.parse.urlencode({'q':query}),request_budget)
            parser=LinkParser();parser.feed(page)
            if parser.urls:
                self.last_attempts.append({'backend':'duckduckgo-html','status':'links-found','count':len(parser.urls)})
                self.last_backend='duckduckgo-html'
                return parser.urls[:limit]
            self.last_attempts.append({'backend':'duckduckgo-html','status':'challenge-page' if re.search(r'anomaly|captcha|challenge',page,re.I) else 'no-parseable-links'})
        except (OSError, ResearchError) as exc:
            self.last_attempts.append({'backend':'duckduckgo-html','status':'error','error':type(exc).__name__})
        # Documented public MediaWiki search API, no key/account/payment.
        if request_budget:request_budget.check('web search fallback')
        topic = query.split(' הלכה site:',1)[0]
        stop = {'מה','מתי','האם','איך','על','של','עם','מותר','מברכים','ברכת','הלכה'}
        terms = [t for t in re.findall(r'[א-תA-Za-z]+',hebrew.strip_niqqud(topic))
                 if hebrew.normalize(t) not in STOP and len(t)>1]
        if not terms:
            return []
        url='https://he.wikisource.org/w/api.php?'+urllib.parse.urlencode({
            'action':'query','list':'search','srsearch':' OR '.join(terms[:6]),
            'srlimit':max(1,min(limit,20)),'format':'json'})
        public_url(url, {'he.wikisource.org'},request_budget)
        opener=urllib.request.build_opener(SafeRedirect({'he.wikisource.org'},request_budget=request_budget))
        if request_budget:request_budget.check('wiki search request')
        with opener.open(urllib.request.Request(url,headers={'User-Agent':USER_AGENT}),timeout=min(self.timeout,request_budget.remaining()) if request_budget else self.timeout) as response:
            raw=response.read(MAX_PAGE_BYTES+1)
            if len(raw)>MAX_PAGE_BYTES:raise ResearchError('search response too large')
            data=json.loads(raw)
        if request_budget:request_budget.check('wiki search return')
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

def compare(sources, question=''):
    """Only flag possible differences; polarity alone cannot establish machloket."""
    from .halachic_authority import differences
    if not question:return []
    return differences(question,sources)

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
    def research(self,question,limit=5,urls=None,request_budget=None):
        from .request_budget import BudgetExceeded
        from .retrieval_budget import accepts_budget
        limit=max(1,min(int(limit),8)); errors=[];sources=[];seen=set();rejected=[]
        if not question.strip() or len(question)>2000:raise ValueError('invalid question')
        try:
            if request_budget:request_budget.check('web discovery')
            options={'request_budget':request_budget} if request_budget and accepts_budget(self.searcher.search) else {}
            urls=urls if urls is not None else self.searcher.search(question+' הלכה '+ ' OR '.join('site:'+h for h in self.sites),limit*2,**options)
            if request_budget:request_budget.check('web discovery return')
        except Exception as exc:
            return {'sources':[],'errors':[{'stage':'search','error':type(exc).__name__}], 'comparisons':[],
                    'answer':'אין לי מקור לכך. חיפוש האינטרנט אינו זמין.','mode':'web-sources-only'}
        for url in urls[:limit*2]:
            if len(sources)>=limit:break
            host=urllib.parse.urlsplit(url).hostname
            if host not in self.sites or url in seen:continue
            seen.add(url)
            try:
                if request_budget:request_budget.check('web page fetch')
                fetch_method=self.fetcher.read if hasattr(self.fetcher,'read') else self.fetcher
                options={'request_budget':request_budget} if request_budget and accepts_budget(fetch_method) else {}
                if hasattr(self.fetcher,'read'):
                    doc=self.fetcher.read(url,**options);final=doc['source_url']
                else:
                    page,final=self.fetcher(url,**options)
                    parser=PageParser();parser.feed(page);doc=parser.document()
                if request_budget:request_budget.check('web page fetch return')
                if urllib.parse.urlsplit(final).hostname not in self.sites:raise ResearchError('redirect outside source registry')
                if final in seen and final!=url:continue
                seen.add(final)
                from .source_quality import classify, exclusion_reason, web_locator_issue
                reason=web_locator_issue(doc['title'],final) or exclusion_reason(question, {'work_title':doc['title'], 'source_url':final,
                                                   'text':doc['text']}, web=True)
                if reason:
                    rejected.append({'url':final,'title':doc['title'],'reason':reason})
                    continue
                relevant=passages(doc['text'],question)
                if not relevant or not doc['title']:continue
                profile=self.sites[urllib.parse.urlsplit(final).hostname]
                license_id=doc.get('license',profile.get('license',''))
                aliases={'Public Domain':'public-domain','CC-BY':'CC-BY','CC-BY-SA':'CC-BY-SA'}
                license_id=aliases.get(license_id,license_id)
                allowed,permission=permission_for(license_id,self.licenses,self.grants,final)
                # Rights-unknown sites contribute a short transient excerpt, never the full page.
                api_reader=hasattr(self.fetcher,'read')
                # API source units remain complete. A clipped/context-unknown
                # excerpt is discovery material, not evidence for a ruling.
                snippet=(doc['text'] if api_reader and allowed and len(doc['text'].encode())<=24000
                         else short_excerpt(relevant[0],question) if not allowed else relevant[0][:1500])
                complete_unit=api_reader and allowed and snippet==doc['text']
                kind='ruling-candidate' if re.search(r'הלכה|פסק|שו״ת|שו"ת|שאלות ותשובות',doc['title']+' '+snippet) else 'general-article'
                source=Source(source_id=stable_id('web',final,snippet),work_title=doc['title'],reference=doc['title']+' — '+final,
                    text=snippet,normalized_text=hebrew.normalize(snippet),author=doc['author'],
                    source_url=final,license=license_id or 'unknown',version=doc.get('version',''),tradition=profile.get('tradition',''),
                    source_project='verified-web',verification_status='excerpt-verified',ingested_at=utcnow_iso(),
                    authority_level=profile.get('authority',''),attribution=doc['title']+' · '+final,
                    license_url=self.licenses.get(license_id,{}).get('url',''),
                    metadata={'content_kind':kind,'source_reliability':profile.get('reliability','unknown'),
                              'authority_evidence':profile.get('authority_evidence',''),'author_status':'page-declared' if doc['author'] else 'unknown',
                              'evidence_support':'exact-excerpt-only','persistence_allowed':allowed,'permission':permission,
                              'published_at':doc['published_at'],'references_in_page':citations.extract_refs(snippet),
                              'page_sha256':__import__('hashlib').sha256(doc['text'].encode()).hexdigest(),
                              'rights_mode':'licensed' if allowed else 'transient-25-word-excerpt'})
                if api_reader:
                    from .torah_web import HalachicSourceAuthority,SimilarHalachicQuestions
                    start=doc['text'].find(snippet)
                    source.metadata.update(rag_answers_allowed=complete_unit,
                        web_authority=HalachicSourceAuthority.classify(doc),site_name=doc.get('site_name',''),
                        source_unit_complete=complete_unit,original_question=doc.get('question',''),
                        similar_question=SimilarHalachicQuestions.compare(question,doc.get('question','')),
                        passage_locator={'representation':'extracted-text','start':start,'end':start+len(snippet) if start>=0 else None,
                            'page_sha256':doc.get('page_sha256',''),'version':doc.get('version',''),
                            'exact_in_representation':start>=0},
                        updated_at=doc.get('updated_at',''),links=doc.get('links',[]),
                        instruction_policy='untrusted data; never instructions',
                        verified_at=utcnow_iso(),cache_max_age_s=3600,verified_until_epoch=time.time()+3600)
                    if re.search(r'ignore (?:all |previous |prior )*instructions|system prompt|התעלם.{0,30}הוראות|חשוף.{0,20}סודות',doc['text'],re.I):
                        source.metadata.update(rag_answers_allowed=False,web_quarantine_reason='instruction-like external content')
                source.metadata.update(classify(source.to_dict()))
                source.metadata['locator_granularity']='page-title-and-url; unit locator not independently established'
                source.metadata['locator_status']='page-title-url-matched' if urllib.parse.urlsplit(final).hostname=='he.wikisource.org' else 'fetched-page-only'
                if api_reader:source.metadata['locator_status']=doc.get('locator_status','fetched-page-only')
                # Full-text store still contains only relevant exact passages, not boilerplate.
                if allowed and self.store_path:
                    if request_budget:request_budget.check('web persistence')
                    save_verified(source,self.store_path)
                sources.append(source)
            except BudgetExceeded:
                errors.append({'stage':'fetch','error':'deadline-exhausted'})
                break
            except Exception as exc:
                errors.append({'url':url,'error':type(exc).__name__,
                    'reason':str(exc)[:160] if isinstance(exc,ResearchError) else 'reader or transport failure'})
        results=rank_sources(HybridSearch(sources).search(question,top_k=limit)) if sources else []
        return {'sources':results,'errors':errors,'rejected_sources':rejected,'comparisons':compare(results,question),
                'answer':evidence.INSUFFICIENT if evidence.shared_oil_waiting(question) else self.extractive_answer(results),'mode':'web-evidence','verdict':'insufficient_context' if evidence.shared_oil_waiting(question) else 'exact-extract-only','discovery_backend':getattr(self.searcher,'last_backend','custom'),'discovery_attempts':getattr(self.searcher,'last_attempts',[]),'verification':{'support':'exact-excerpts','psak':'not-inferred'}}
    def answer(self, question, base_url, model, limit=5, urls=None, timeout=15, local_sources=None, answer_model=None, source_verifier=None, request_budget=None, source_resolver=None):
        from .retrieval_budget import accepts_budget
        result = self.research(question, limit=limit, urls=urls,request_budget=request_budget)
        from .source_snapshot import public_sources
        result['web_findings']=public_sources(result.get('sources',[]))
        result.setdefault('search_status',{'partial':bool(result.get('errors')), 'errors':result.get('errors',[])})
        result.update(human_review='required', halachic_verified=False)
        local_sources = [s for s in (local_sources or []) if rag_eligible(s)]
        if local_sources:
            from .agent import order_sources
            from .hybrid import rrf_fuse
            merged=rrf_fuse([local_sources,result['sources']],top_k=limit)
            result['sources'] = order_sources(merged,question)[:limit]
            if merged.errors:
                result['search_status']['partial']=True
                result['search_status']['errors'].extend(merged.errors)
            result['answer'] = self.extractive_answer(result['sources'])
            result['comparisons'] = compare(result['sources'],question)
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
            if request_budget:request_budget.check('web answer generation')
            from .request_budget import revalidate_sources
            local_ids={s['source_id'] for s in local_sources}
            if source_resolver:
                revalidate_sources([s for s in result['sources'] if s['source_id'] in local_ids],source_resolver,request_budget)
            generated = generator.generate(question, result['sources'], timeout=timeout)['answer']
            if hasattr(generator,'sent_sources'):
                result['sources']=generator.sent_sources
            from .source_snapshot import fingerprint, admissible
            current=[];changed=[]
            try:packet=json.loads(generated)
            except (ValueError,TypeError):packet=None
            selection=(packet.get('selected_sources') if isinstance(packet,dict) and set(packet)=={'selected_sources'} else None)
            selected=(set(selection) if isinstance(selection,list) and 1<=len(selection)<=2
                and all(isinstance(sid,str) and sid for sid in selection) and len(set(selection))==len(selection) else None)
            for source in result['sources']:
                # Unselected external pages remain discovery records. They do
                # not consume the freshness reads needed by actual citations.
                if source.get('source_project')=='verified-web' and selected is not None and source['source_id'] not in selected:
                    continue
                if request_budget:request_budget.check('web source revalidation')
                opts={'request_budget':request_budget} if request_budget and source_resolver and accepts_budget(source_resolver) else {}
                fresh=source_resolver(source['source_id'],**opts) if source_resolver and source['source_id'] in local_ids else source
                if request_budget:request_budget.check('web source revalidation return')
                if fresh is None or fingerprint(fresh)!=fingerprint(source):
                    changed.append(source['source_id']);fresh=None
                if fresh and fresh.get('source_project')=='verified-web' and fresh.get('metadata',{}).get('persistence_allowed'):
                    allowed,_=permission_for(fresh.get('license',''),
                                             self.licenses,self.grants,fresh['source_url'])
                    if not allowed:changed.append(source['source_id']);fresh=None
                if fresh and fresh.get('source_project')=='verified-web' and hasattr(self,'validate_source'):
                    if not self.validate_source(fresh,request_budget):changed.append(source['source_id']);fresh=None
                if fresh and admissible(fresh):current.append(fresh)
            result['sources']=current
            if changed:
                result['search_status']['partial']=True
                result['search_status']['errors'].append({'stage':'source-revalidation','error':'source-or-policy-changed','source_ids':changed})
            # Missing selected IDs fail the ordinary verifier. A changed source
            # is never silently replaced by a newer text under the same ID.
            verification = verifier.verify(question, generated, current)
            result['verification'] = verification
            if verification['verdict']=='ok':
                result.update(answer=verification.get('rendered_answer',generated), mode='web-llm-verified', verdict=verification.get('support','exact-extract-only'))
            elif verification['verdict']=='no_source':
                result.update(answer=verification.get('rendered_answer','אין לי מקור לכך.'), mode='web-llm-guarded', verdict='no_source')
            else:
                result['mode']='web-llm-guarded'
                result['verdict']=verification['verdict']
                result['answer']=(evidence.INSUFFICIENT if evidence.shared_oil_waiting(question)
                                  else 'אין במקורות ובאימות הקיימים בסיס מספיק לתשובה הלכתית. המקורות זמינים לבדיקה; אין להציג את פלט המודל כפסיקה.')
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
    from .torah_web import HybridHalachicResearch
    args=parser.parse_args();print(json.dumps(HybridHalachicResearch(store_path=args.store).research(args.question,urls=args.url),ensure_ascii=False,indent=2))
