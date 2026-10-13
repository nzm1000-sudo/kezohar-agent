"""Literal book/siman/seif lookup in existing metadata, no inferred locators."""
import re
from .hebrew import normalize
WORKS={'ילקוט יוסף':('ילקוט יוסף','קיצור שולחן ערוך – ילקוט יוסף'),
       'שולחן ערוך':('שולחן ערוך','שולחן ערוך, אורח חיים'),
       'בית יוסף':('בית יוסף',),'בן איש חי':('בן איש חי',)}
VALUES=dict(zip('אבגדהוזחטיכלמנסעפצקרשת',(1,2,3,4,5,6,7,8,9,10,20,30,40,50,60,70,80,90,100,200,300,400)))

def number(label):
    value=normalize(label)
    if value.isascii() and value.isdigit():return int(value)
    if not value or any(c not in VALUES for c in value):return None
    return sum(VALUES[c] for c in value)  # exact numeric notation, not guessed source numbering

def fields(text):
    q=normalize(text)
    if 'סעיפ קטנ' in q or re.search(r'\bסק\b',q):return None
    if re.search(r'(?:סימן|סי[׳\'])\s+[א-ת\"״׳0-9]+\s*[-–—]',text):return None
    match=re.search(r'(?:סימנ|סי)\s+([א-ת0-9]+).*?(?:סעיפ|סק)\s+([א-ת0-9]+)',q)
    if match:return number(match[1]),number(match[2])
    match=re.search(r'([א-ת\"״׳0-9]+):([א-ת\"״׳0-9]+)',text)
    return (number(match[1]),number(match[2])) if match else None

def reference_only(question):
    hint=parse(question)
    if not hint:return False
    q=normalize(question)
    for word in (hint['work'],hint['division'] or ''):
        if word:q=q.replace(normalize(word),' ')
    q=re.sub(r'(?:סימנ|סי)\s+[א-ת0-9]+\s+(?:סעיפ)\s+[א-ת0-9]+',' ',q)
    return all(w in ('פתח','הצג','את','המקור','מקור','טקסט','של','ספר','בבקשה') for w in q.split())

def parse(question):
    work=next((w for w in WORKS if normalize(w) in normalize(question)),None)
    loc=fields(question)
    if not work or not loc or None in loc:return None
    division=next((v for v in ('אורח חיים','יורה דעה','אבן העזר','חושן משפט') if normalize(v) in normalize(question)),None)
    return {'work':work,'siman':loc[0],'seif':loc[1],'division':division,'literal':question}

def matches(source,hint):
    if not hint:return False
    if normalize(source.get('work_title','')) not in {normalize(w) for w in WORKS[hint['work']]}:return False
    if hint['division'] and normalize(hint['division']) not in normalize(source.get('reference','')):return False
    return fields(source.get('reference',''))==(hint['siman'],hint['seif'])

def lookup(knowledge,question,budget=None):
    hint=parse(question)
    if not hint:return []
    out=[];primary=getattr(knowledge.search,'primary',knowledge.search)
    for item in getattr(getattr(primary,'bm25',None),'docs',[]):
        if budget:budget.check('locator primary scan')
        s=item.to_dict()
        if matches(s,hint):out.append(s)
    for backend in getattr(knowledge.search,'backends',[]):
        call=getattr(backend,'lookup_locator',None)
        if call:
            if budget:budget.check('locator disk lookup')
            out.extend(call(hint,request_budget=budget))
    return out
