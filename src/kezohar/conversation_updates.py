"""Shared explicit follow-up updates. User facts never become source evidence."""
import re
from .hebrew import normalize

def explicit_updates(question,intent):
    q=normalize(question);facts={}
    if intent in ('yaaleh-shachrit','yaaleh-general'):
        for word,value in [('ראש חודש','rosh_chodesh'),('חול המועד','chol_hamoed'),('יומ טוב','festival')]:
            if word in q:facts['prayer_occasion']=value
        for word,value in [('שחרית','shachrit'),('מנחה','mincha'),('ערבית','arvit')]:
            if re.search(r'(?<!לא )(?<!לא ב)\bב?'+word+r'\b',q):facts['prayer_service']=value
        if any(w in q for w in ('כבר סיימתי','סיימתי את התפילה','עקרתי רגל')):facts['prayer_stage']='finished'
        elif 'עדיינ באמצע' in q:facts['prayer_stage']='during'
    if intent=='shared-oil' and 'פירור' in q:
        if 'לא נשארו' in q or 'בלי פירור' in q:facts['oil_residue']='absent'
        elif 'נשארו' in q or 'יש פירור' in q:facts['oil_residue']='present'
    return facts

def corrected_root(root,question,updates):
    if (re.search(r'בעצם|תיקון|טעיתי|התכוונתי',question) and 'prayer_service' in updates):
        return re.sub(r'(?<!\w)ב?(?:שחרית|מנחה|ערבית)(?!\w)','',root)
    return root

def browser_turn(question,history,circumstances=None):
    if (not isinstance(history,list) or len(history)>8
            or any(not isinstance(q,str) or not q.strip() or len(q)>2000 for q in history)
            or sum(map(len,history))>6000):raise ValueError('invalid temporary conversation history')
    if not history:return question,circumstances,{'followup':False,'persistent':False}
    from .question_understanding import analyze
    root=history[0];intent=analyze(root)['intent'];incoming=analyze(question)['intent'];facts={}
    if incoming!='general-halacha' and incoming!=intent and not re.search(r'בעצם|תיקון|זה היה|כבר סיימתי|ואם',question):
        return question,circumstances,{'followup':False,'persistent':False,'new_case_detected':True}
    for turn in history[1:]+[question]:
        updates=explicit_updates(turn,intent)
        root=corrected_root(root,turn,updates);facts.update(updates)
    facts.update(circumstances or {})
    effective=root+'\nפרטי המשך מפי המשתמש בלבד; אינם ראיות:\n'+'\n'.join(history[1:]+[question])
    return effective,facts,{'followup':True,'persistent':False,'history_is_evidence':False,
                          'original_turn':question,'explicit_updates':facts}
