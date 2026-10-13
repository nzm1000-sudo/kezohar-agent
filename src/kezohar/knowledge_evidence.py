"""Necessary evidence-kind filters. Never an automatic entailment approval."""
import re
from .hebrew import normalize
from .jewish_encyclopedia import ALIASES

def expected_kind(question,route):
    q=normalize(question)
    if route['relation']:return 'explicit-relationship'
    if q.startswith(('מי היה','מי היתה','מי הייתה')):return 'biography'
    if 'מה ההבדל' in q:return 'concept-comparison'
    if any(w in q for w in ('מה פירוש','פירוש המילה','מהי ','מהנ ','מהו ')):return 'definition'
    if q.startswith(('מדוע','למה')) or ('לא נכנס' in q and any(w in q for w in ('פירוש','פירושימ','מחקר'))):return 'causal-explanation'
    return 'source-reading'

def issue(question,route,source):
    kind=expected_kind(question,route);t=normalize(source.get('text',''));q=normalize(question)
    if kind=='biography':
        entity=route.get('entity');name=normalize(ALIASES.get(entity,entity or ''))
        if not name or name not in normalize(source.get('work_title','')):
            return 'a mention in someone else’s work is not a biography'
        if not any(w in t[:600] for w in ('היה','הוא','פוסק','מחבר','רב','תנא','אמורא','מקובל')):
            return 'identity description absent'
    if kind=='definition':
        match=re.search(r'(?:המילה|המושג)\s+([א-ת]+)',q)
        term=match[1] if match else next((normalize(w) for w in ('עשר הספירות','תיקו','תקופת הגאונים','הבהיר') if normalize(w) in q),None)
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
