"""Bounded HTML-library adapter. Scripts are parsed as data, never executed.

Discovery follows published AddIndex links. Citations preserve original named
anchors; no inference of siman/seif from ordinal position or filenames.
"""
import hashlib
import re
import urllib.parse
from html import unescape
from html.parser import HTMLParser
from .hebrew import normalize
from .web_research import ResearchError

BASE='https://www.toratemetfreeware.com/online/'

def checked_url(url):
    p=urllib.parse.urlsplit(url)
    if (p.scheme!='https' or p.netloc!='www.toratemetfreeware.com' or p.query
            or not re.fullmatch(r'/online/(?:|d_[A-Za-z0-9_]+\.html|f_\d+\.html)',p.path)):
        raise ResearchError('invalid Torat Emet library locator')
    return url

def entries(html):
    # Restrict to literal three-string calls; no eval/JS/runtime dependency.
    return [{'title':unescape(t),'url':checked_url(BASE+path),'kind':kind}
        for t,path,kind in re.findall(r'AddIndex\("([^"\\\r\n]+)",\s*"([A-Za-z0-9_]+\.html)",\s*"(folder|book|splited_book)"\)',html)]

class _Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('br','p','hr'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
    def text(self):return re.sub(r'\s+',' ',' '.join(self.parts)).strip()

def documents(html,url):
    checked_url(url)
    title=re.search(r'<title[^>]*>(.*?)</title>',html,re.I|re.S)
    if not title or '<!--BODY_START-->' not in html:raise ResearchError('unrecognized Torat Emet book layout')
    name=unescape(title[1]).strip()
    if '<!--BODY_END-->' not in html:raise ResearchError('incomplete Torat Emet book body')
    body=html.split('<!--BODY_START-->',1)[1].split('<!--BODY_END-->',1)[0]
    anchors=list(re.finditer(r'<a\s+name="([^"<>]*B[^"<>]+)"\s*>\s*</a>',body,re.I))
    names=[m[1] for m in anchors]
    if not anchors or len(set(names))!=len(names):raise ResearchError('missing or duplicate book anchors')
    digest=hashlib.sha256(html.encode()).hexdigest();out=[]
    credit_parser=_Text();credit_parser.feed(html.split('<!--BODY_START-->',1)[0])
    credit_match=re.search(r'כל הזכויות שמורות.{0,180}?(?=תורה|פרשת|שמות|$)',credit_parser.text())
    credit=credit_match[0].strip() if credit_match else 'תורת אמת — ייחוס נוסף לא זוהה בדף'
    for i,m in enumerate(anchors):
        parser=_Text();parser.feed(body[m.end():anchors[i+1].start() if i+1<len(anchors) else len(body)])
        text=parser.text()
        if not 8<=len(text)<=1800:continue
        locator=m[1].replace('B',' ')
        out.append({'title':name,'reference':locator,'text':text,'author':'','author_status':'not-established',
            'source_url':url.split('#')[0]+'#'+urllib.parse.quote(m[1],safe=''),
            'version':'Torat Emet HTML sha256:'+digest,'page_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'site_name':'תורת אמת','license':'','license_status':'owner-confirmed-noncommercial',
            'attribution':credit,'license_url':BASE+'a_wellcome.html',
            'source_unit_complete':False,
            'locator_status':'original-named-anchor; canonical-numbering-not-inferred',
            'primary_kind':'text','version_source':url.split('#')[0]})
    return out

class ToratEmetAdapter:
    def __init__(self,transport):self.transport=transport;self.errors=[];self.attempts=[]
    def read(self,url,budget=None):
        checked_url(url);p=urllib.parse.urlsplit(url)
        if not p.fragment:raise ResearchError('Torat Emet evidence requires an exact named anchor')
        html=self.transport.html(urllib.parse.urlunsplit(p._replace(fragment='')),budget)
        docs=documents(html,urllib.parse.urlunsplit(p._replace(fragment='')))
        found=[d for d in docs if urllib.parse.unquote(urllib.parse.urlsplit(d['source_url']).fragment)==urllib.parse.unquote(p.fragment)]
        if len(found)!=1:raise ResearchError('book anchor not uniquely confirmed')
        return found[0]
    def search(self,question,route,budget,limit=3):
        # No question/history is sent to the site: only published index paths.
        from .jewish_web import knowledge_queries
        queries=knowledge_queries(question,route)
        if not queries:return []
        from .knowledge_catalog import catalog_matches
        terms=list(dict.fromkeys(normalize(t) for t in route.get('public_entities',[])+
            [b['heTitle'] for b in catalog_matches(route['normalized_question'])]))
        if not terms:terms=list(dict.fromkeys(normalize(q) for q in queries))
        queue=[(BASE,0)];books=[];seen=set();pages=0
        while queue and pages<5:
            url,depth=queue.pop(0)
            if url in seen:continue
            seen.add(url);budget.check('Torat Emet index discovery')
            html=self.transport.html(url,budget);pages+=1
            for entry in entries(html):
                title=normalize(entry['title'])
                if entry['kind']=='folder':
                    # Root domain selection precedes title matching; bounded,
                    # breadth-first discovery, never a whole-library crawler.
                    domains=route.get('domains',[])
                    root_ok=(('tanakh' in domains and title in {normalize(x) for x in ('תורה','נביאים','כתובים')})
                        or ('halacha' in domains and 'הלכה' in title)
                        or ('chasidut' in domains and 'חסידות' in title)
                        or ('kabbalah' in domains and 'קבלה' in title))
                    if (depth==0 and root_ok) or (depth>0 and any(t in title or title in t for t in terms)):
                        if depth<3:queue.append((entry['url'],depth+1))
                elif any(t in title or title in t for t in terms):books.append(entry)
        hits=[]
        for book in books[:2]:
            budget.check('Torat Emet book discovery')
            try:docs=documents(self.transport.html(book['url'],budget),book['url'])
            except (OSError,ValueError,ResearchError) as exc:
                self.errors.append({'stage':'torat-emet-book','reason':str(exc)[:120]});continue
            for doc in docs:
                text=normalize(doc['text']);title=normalize(book['title'])
                score=max((sum(t in text or t in title for t in normalize(q).split()) for q in queries),default=0)
                if score>=min(2,max(len(normalize(q).split()) for q in queries)):hits.append((score,doc['source_url']))
        self.attempts.append({'backend':'torat-emet-html','index_pages':pages,'books_read':min(2,len(books)),'matching_units':len(hits)})
        return [url for _,url in sorted(hits,key=lambda h:-h[0])[:limit]]
