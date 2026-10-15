"""Public licensed encyclopedia introductions, explicitly secondary evidence."""
import hashlib,urllib.parse
from .jewish_web import source_from_doc
from .torah_web import PublicApiTransport,ResearchError
from .question_intent import PUBLIC_ENTITIES,PUBLIC_TOPICS

ALIASES={'החיד״א':'חיים יוסף דוד אזולאי','החידא':'חיים יוסף דוד אזולאי','הרמב״ם':'משה בן מימון',
         'הרמבם':'משה בן מימון','הרמב״ן':'משה בן נחמן','רשב״א':'שלמה בן אדרת',
         'רבי נחמן מברסלב':'נחמן מברסלב','הבעל שם טוב':'ישראל בן אליעזר'}

class JewishEncyclopediaEngine:
    def __init__(self,transport=None,licenses=None):self.transport=transport or PublicApiTransport();self.licenses=licenses
    def search(self,route,budget,limit=2):
        if route.get('export_allowed') is False:return []
        from .knowledge_catalog import catalog_matches
        from .torah_domains import TOPICS
        import re
        from .jewish_web import question_keywords
        q=route['normalized_question']
        terms=[t for t in PUBLIC_ENTITIES+PUBLIC_TOPICS+TOPICS
               if re.search(r'(?<![א-ת])[ובהלמש]?'+re.escape(t)+r'(?![א-ת])',q)]+[r['heTitle'] for r in catalog_matches(q)]
        definition=route.get('definition_request')
        if definition and definition['id']:
            terms=[definition['queries'][0].split(' דהיינו')[0]]
        elif definition and definition.get('target'):
            terms=[definition['target']]
        # Owner decision 2026-10-15: the question's own subject goes to the encyclopedia when nothing is registered.
        entity=route.get('entity')
        if entity and not terms:terms=[entity]
        if not terms:
            keywords=question_keywords(q)
            terms=[keywords] if keywords else []
        if not terms:return []
        term=next(iter(sorted(terms,key=len,reverse=True)))
        term=ALIASES.get(term,term)
        if term=='תיקו' and 'talmud' in route['domains']:term+=' תלמוד'
        elif 'משנה' in terms and 'גמרא' in terms:term='משנה תלמוד'
        data=self.transport.json('https://he.wikipedia.org/w/api.php?'+urllib.parse.urlencode({
            'action':'query','list':'search','srsearch':term,'srlimit':limit,'srnamespace':0,'format':'json','maxlag':5}),request_budget=budget)
        return [r['title'] for r in data.get('query',{}).get('search',[])][:limit]
    def read(self,title,budget):
        data=self.transport.json('https://he.wikipedia.org/w/api.php?'+urllib.parse.urlencode({
            'action':'query','titles':title,'prop':'extracts|info|revisions|pageprops','exintro':1,'explaintext':1,
            'inprop':'url','rvprop':'ids','redirects':1,'format':'json','maxlag':5}),request_budget=budget)
        pages=list(data.get('query',{}).get('pages',{}).values())
        if len(pages)!=1:raise ResearchError('encyclopedia page ambiguous')
        page=pages[0]
        if 'missing' in page or page.get('ns')!=0 or 'disambiguation' in page.get('pageprops',{}):raise ResearchError('encyclopedia page missing or disambiguation')
        revisions=page.get('revisions',[])
        if not revisions or not page.get('extract'):raise ResearchError('encyclopedia revision unavailable')
        text=page['extract'];url=page.get('fullurl','')
        if not url.startswith('https://he.wikipedia.org/wiki/'):raise ResearchError('encyclopedia URL mismatch')
        doc={'title':page['title'],'reference':page['title']+' — ויקיפדיה, גרסה '+str(revisions[0]['revid']),
            'text':text,'version':'Wikipedia revision '+str(revisions[0]['revid']),
            'source_url':url,'license':'CC-BY-SA','primary_kind':'secondary-encyclopedia',
            'site_name':'ויקיפדיה','locator_status':'official-api-page-revision',
            'page_sha256':hashlib.sha256(text.encode()).hexdigest()}
        source=source_from_doc(doc,self.licenses)
        if source:source['metadata'].update(license_evidence='https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use',
            quotation_kind='secondary encyclopedia introduction; not a ruling',encyclopedia_title=page['title'])
        return source
