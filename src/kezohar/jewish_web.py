"""Public Torah knowledge search using the same pinned/rate-limited transport."""
import hashlib,json,re,urllib.parse
from . import hebrew
from .models import Source,stable_id,utcnow_iso
from .permissions import permission_for
from .ingest import load_licenses
from .torah_web import PublicApiTransport,TorahWebReader,ResearchError,canonical_url
from .question_intent import PUBLIC_ENTITIES,PUBLIC_TOPICS

def knowledge_queries(question,route):
    if route.get('export_allowed') is False:return []
    # Only registered editorial terms may be exported; arbitrary definition
    # targets, private names and previous conversation text remain local.
    definition=route.get('definition_request')
    if definition and definition['id']:return list(definition['queries'])
    q=route['normalized_question'];names=[n for n in PUBLIC_ENTITIES if n in q]
    from .knowledge_catalog import catalog_matches
    from .torah_domains import TOPICS
    topics=[t for t in PUBLIC_TOPICS+TOPICS if t in q]+[r['heTitle'] for r in catalog_matches(q)]
    modifiers={'חסידות','ברסלב','חב״ד','קבלה','מוסר'}
    substantive=[t for t in topics if t not in modifiers]
    if substantive:topics=substantive
    if not names and not topics:return []
    terms=list(dict.fromkeys(names+topics))[:4]
    relation={'father':['ותלד','בני'],'mother':['ותהר','אם'],'wife':['אשתו','לאשה'],
              'son':['בן','בני'],'teacher':['תלמיד','למד'],'author':['מחבר'],'child-count':['בני']}
    queries=[' '.join(terms+[term]) for term in relation.get(route['relation'],[''])]
    if route['relation']=='child-count' and route['entity']:
        queries=['בני '+route['entity']+' שנים','בני '+route['entity']]
    if 'tanakh' in route['domains'] and 'לא נכנס' in q and names:
        queries=[names[0]+' לא תביאו',queries[0]]
    if 'ברכה' in q:queries+=[' '.join(terms+['ברכה'])]
    return list(dict.fromkeys(queries))[:2]

def source_from_doc(doc,licenses=None):
    licenses=load_licenses() if licenses is None else licenses
    license_id={'Public Domain':'public-domain'}.get(doc.get('license',''),doc.get('license',''))
    allowed,permission=permission_for(license_id,licenses,{},doc['source_url'])
    from .source_registry import owner_authorization
    declared=owner_authorization(doc['source_url'])
    if declared:allowed,permission=True,declared
    if not allowed or not doc.get('version') or len(doc.get('text','').encode())>32000:return None
    meta={'rag_answers_allowed':True,'source_unit_complete':doc.get('source_unit_complete',True),'permission':permission,
        'page_sha256':doc['page_sha256'],'knowledge_primary_kind':doc.get('primary_kind','text'),
        'site_name':doc.get('site_name',''),'locator_status':doc.get('locator_status'),
        'source_reliability':('public HTML library' if doc.get('site_name')=='תורת אמת' else 'official API')+'; meaning separately checked','instruction_policy':'untrusted-data',
        'source_api_url':doc.get('source_api_url','')}
    if doc.get('license_url'):meta['license_url']=doc['license_url']
    if doc.get('attribution'):meta['original_attribution']=doc['attribution']
    from .knowledge_catalog import source_catalog_entry
    from .torah_domains import source_genre
    entry=source_catalog_entry(doc['source_url'])
    if entry:
        meta.update(knowledge_categories=entry['categories'],knowledge_genre=source_genre(entry['categories'],entry['title']))
    if re.search(r'ignore (?:all |previous )*instructions|system prompt|התעלם.{0,30}הוראות',doc['text'],re.I):return None
    return Source(source_id=stable_id('jewish-knowledge',doc['source_url'],doc['text']),work_title=doc['title'],
        reference=doc.get('reference',doc['title']),text=doc['text'],normalized_text=hebrew.normalize(doc['text']),
        version=doc['version'],license=license_id,source_url=doc['source_url'],source_project='jewish-knowledge-web',
        attribution=doc.get('attribution',doc['title'])+' · '+doc['source_url']+' · '+doc['version'],
        ingested_at=utcnow_iso(),metadata=meta).to_dict()

class JewishKnowledgeWebSearch:
    def __init__(self,transport=None,licenses=None):
        self.transport=transport or PublicApiTransport(max_requests=12);self.licenses=licenses
        self.reader=TorahWebReader(self.transport);self.attempts=[];self.errors=[]
    def search(self,question,route,budget,limit=6):
        queries=knowledge_queries(question,route);urls=[]
        from .knowledge_catalog import catalog_matches
        named_books=catalog_matches(route['normalized_question'])
        filters=[]
        if 'tanakh' in route['domains'] and (route['relation'] in ('father','mother','wife','child-count','children') or route['kind']=='interpretation' or route.get('identity_request')):filters=['Tanakh']
        elif 'chasidut' in route['domains'] or 'traditional-narrative' in route['domains']:filters=['Chasidut']
        elif 'kabbalah' in route['domains']:filters=['Kabbalah']
        elif 'jewish-thought' in route['domains']:filters=['Musar','Jewish Thought']
        for query in queries:
            budget.check('knowledge web search')
            try:
                data=self.transport.json('https://www.sefaria.org/api/search-wrapper',
                    {'query':query,'type':'text','field':'naive_lemmatizer','slop':30,'size':min(30,limit*4),
                     'source_proj':['ref','heRef','title','categories'],
                     **({'filters':filters,'filter_fields':['path']*len(filters)} if filters else {})},budget)
                hits=data.get('hits',{}).get('hits',[])
                # Primary biblical text first for biblical family facts.
                def named_hit(hit):
                    ref=hit.get('_source',{}).get('ref','')
                    return any(ref==b['title'] or ref.startswith(b['title']+',') or ref.startswith(b['title']+' ') or ref.startswith(b['title']+'.') for b in named_books)
                hits=sorted(hits,key=lambda h:(bool(named_books) and not named_hit(h),'Tanakh' not in h.get('_source',{}).get('categories',[])))
                urls.extend('https://www.sefaria.org/'+urllib.parse.quote(h['_source']['ref'].replace(' ','_'))
                    for h in hits if h.get('_source',{}).get('ref'))
                self.attempts.append({'query':query,'backend':'sefaria-official','count':len(hits)})
            except (OSError,ValueError,ResearchError) as exc:self.errors.append({'stage':'search','reason':str(exc)[:120]})
        # Torat Emet supplies additional candidates when the API returned no
        # candidates, or the requested book was explicitly named. It shares the
        # same root request budget and cannot turn a failed search into success.
        if not urls or 'תורת אמת' in question:
            from .torat_emet import ToratEmetAdapter
            adapter=ToratEmetAdapter(self.transport)
            try:urls=adapter.search(question,route,budget,limit=2)+urls
            except (OSError,ValueError,ResearchError) as exc:self.errors.append({'stage':'torat-emet-search','reason':str(exc)[:120]})
            self.attempts.extend(adapter.attempts)
            self.errors.extend(adapter.errors)
        return list(dict.fromkeys(urls))[:limit]
    def read(self,url,budget):
        doc=self.reader.read(url,budget)
        ref=urllib.parse.unquote(urllib.parse.urlsplit(url).path[1:]).replace('_',' ')
        if re.match(r'(?:Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|[IV]+ Samuel|[IV]+ Kings|Isaiah|Jeremiah|Ezekiel|Ruth|Esther|[IV]+ Chronicles)\s+\d',ref):
            doc['primary_kind']='biblical-text'
        return source_from_doc(doc,self.licenses)
    def index(self,title,budget):
        # Index metadata is not the book's copyrighted body text. Keep only
        # factual title/author fields exposed by the documented public API.
        data=self.transport.json('https://www.sefaria.org/api/index/'+urllib.parse.quote(title,safe=''),request_budget=budget)
        if data.get('title')!=title:raise ResearchError('book identity mismatch')
        authors=[a['he'] for a in data.get('authors',[]) if isinstance(a,dict) and a.get('he')]
        if not authors:return None
        text=json.dumps({'title':data.get('heTitle',title),'authors':authors},ensure_ascii=False,sort_keys=True)
        url='https://www.sefaria.org/'+urllib.parse.quote(title.replace(' ','_'))
        permission={'status':'documented-public-api-metadata','evidence':'https://developers.sefaria.org/reference/get-index',
            'scope':{'metadata_only':True,'book_text':False},'attribution_required':True}
        return Source(source_id=stable_id('book-metadata',url,text),work_title=data.get('heTitle',title),author='; '.join(authors),reference=data.get('heTitle',title)+' — רשומת ספריא',
            text=text,normalized_text=hebrew.normalize(text),version='API metadata '+hashlib.sha256(text.encode()).hexdigest()[:12],
            license='public-api-metadata-only',source_url=url,source_project='jewish-knowledge-web',
            attribution='ספריא · '+url,metadata={'rag_answers_allowed':True,'knowledge_primary_kind':'bibliographic-metadata',
                'locator_status':'official-api-index','permission':permission,'site_name':'ספריא','page_sha256':hashlib.sha256(text.encode()).hexdigest()}).to_dict()
