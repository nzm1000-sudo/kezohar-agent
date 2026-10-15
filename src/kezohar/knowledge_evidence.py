"""Necessary evidence-kind filters. Never an automatic entailment approval."""
import re
from .hebrew import normalize
from .jewish_encyclopedia import ALIASES

def expected_kind(question,route):
    q=normalize(question)
    if route['relation']:return 'explicit-relationship'
    if 'traditional-narrative' in route['domains']:return 'traditional-narrative'
    if q.startswith(('מי היה','מי היתה','מי הייתה')):return 'biography'
    if 'מה ההבדל' in q:return 'concept-comparison'
    if any(w in q for w in ('מה פירוש','פירוש המילה','מהי ','מהנ ','מהו ')):return 'definition'
    if q.startswith(('מדוע','למה')) or ('לא נכנס' in q and any(w in q for w in ('פירוש','פירושימ','מחקר'))):return 'causal-explanation'
    return 'source-reading'

def issue(question,route,source):
    kind=expected_kind(question,route);t=normalize(source.get('text',''));q=normalize(question)
    if kind=='traditional-narrative' and (len(source.get('text',''))<80 or len(t.split())<12):
        return 'a short title is not a narrative excerpt'
    from .knowledge_catalog import catalog_matches,source_catalog_entry
    requested=catalog_matches(route['normalized_question'])
    if requested and re.search(r'מתוך|מה אומר|בספר|לפי הספר',route['normalized_question']):
        entry=source_catalog_entry(source.get('source_url',''))
        title=normalize(source.get('work_title',''))
        belongs=any((entry and entry['title']==book['title']) or title==normalize(book['heTitle'])
                    or title.startswith(normalize(book['heTitle'])+' ') for book in requested)
        if not belongs:return 'a mention of the requested book is not a passage from that book'
        if source.get('metadata',{}).get('knowledge_primary_kind')=='secondary-encyclopedia':
            return 'an encyclopedia summary is not the requested book excerpt'
    if kind=='biography':
        entity=route.get('entity');name=normalize(ALIASES.get(entity,entity or ''))
        if not name or name not in normalize(source.get('work_title','')):
            return 'a mention in someone else’s work is not a biography'
        if not any(w in t[:600] for w in ('היה','הוא','פוסק','מחבר','רב','תנא','אמורא','מקובל')):
            return 'identity description absent'
    if kind=='definition':
        match=re.search(r'(?:המילה|המושג)\s+([א-ת]+)',q)
        term=match[1] if match else next((normalize(w) for w in ('עשר הספירות','תיקו','תקופת הגאונים','הבהיר') if normalize(w) in q),None)
        if term is None:
            definition=re.match(r'(?:מהי|מהו|מהנ|מהמ)\s+([א-ת]+(?:\s+[א-ת]+){0,2}?)(?=\s+(?:ב[א-ת]+|לפי|על פי)|\?|$)',q)
            if definition:term=definition[1]
        if term is None:
            phrase=re.match(r'(?:מה פירוש(?: הביטוי)?|מה משמעות(?: הביטוי)?|מהו|מהי)\s+(.+?)(?=\s+(?:בגמרא|לפי|על פי)|\?|$)',q)
            if phrase:term=phrase[1].strip()
        if term is None:return 'the requested definition target is unresolved'
        if term=='עשר הספירות' and 'ספירה' in normalize(source.get('work_title','')):term='ספירה'
        if term:
            if not re.search(re.escape(term)+r'.{0,120}(?:פירוש|משמעות|מונח|כלומר|הוא|היא|הנ |בארמית|מושג|תעמוד|לא הוכרע)|(?:פירוש|משמעות|מונח|מושג).{0,100}'+re.escape(term),t):
                return 'term use is not a definition'
        if term=='תיקו' and 'גמרא' in q and not any(w in t for w in ('תלמוד','גמרא','ארמית','סוגיה')):
            return 'modern sports sense is not the requested Talmudic meaning'
    if kind=='concept-comparison':
        if 'משנה' in q and 'גמרא' in q:
            if not ('משנה' in t and ('גמרא' in t or 'תלמוד' in t)
                    and any(w in t for w in ('פרשנות','מפרש','דיונ','פירוש','משנה וגמרא','מהווה','החלק'))):
                return 'both concepts and their relationship are required'
    if kind=='causal-explanation':
        if not all(normalize(name) in t for name in route.get('public_entities',[])):
            return 'the requested actor is absent; topic overlap is not a cause'
        if not any(w in t for w in ('יענ','מפני','משומ','לכנ','כי','סיבה','טעמ')):
            return 'a mention of the event is not an explanation'
    return None

def selection_key(question,route,source):
    """Rank a focused evidence passage, never mention frequency in a book."""
    from .jewish_web import knowledge_queries
    from .knowledge_units import units
    queries=knowledge_queries(question,route)
    tokens=set(normalize(' '.join(queries)).split())
    passages=[u['text'] for u in units(source)]
    relevant=[p for p in passages if not issue(question,route,dict(source,text=p))]
    coverage=max((len(tokens.intersection(normalize(p).split())) for p in relevant),default=0)
    primary=source.get('metadata',{}).get('knowledge_primary_kind')
    return (not bool(relevant),-coverage,
        'tanakh' in route['domains'] and primary!='biblical-text',
        expected_kind(question,route) in ('biography','definition') and primary!='secondary-encyclopedia',
        len(source.get('text','')))
