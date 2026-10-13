"""Explainable linguistic evidence, independent of halachic judgment.

Spans are user wording, never source evidence. Ambiguous negation, tense and
relations stay unresolved; an optional model may only propose interpretations.
"""
import re
from .hebrew import normalize

ACTION_PATTERNS={
    'bless':r'בירכתי|ברכתי|לברך|מברכים|מברך|ברכת',
    'eat':r'אכלתי|לאכול|אכילת|אוכלים',
    'wear-tefillin':r'מניחים\s+תפילין|להניח\s+תפילין|הנחת\s+תפילין',
    'remove-tefillin':r'לחלוץ|חליצת|חולצים|חולץ',
    'speak':r'לדבר|דיברתי|לשוחח|לפטפט|דיבור|הפסקתי',
    'heat':r'לחמם|חיממתי|חימום|לבשל|בישול',
    'immerse':r'לטבול|טבלתי|טבילת|להטביל|הטבלתי',
    'light':r'להדליק|הדלקתי|מדליקים|הדלקת',
    'pray':r'התפללתי|להתפלל|אומרים|לומר|תפילת|תפילה',
}
TOPICS={
    'blessings':r'ברכ|מברכ|מזון|מזונ|נפשות|פקאן|אורז',
    'prayer':r'תפל|תפיל|יעלה|קדיש|שמע',
    'shabbat':r'שבת|פלטה|מיחם|מיחמ',
    'meat-milk':r'בשר|שניצל|חלב|גבינה|שמנ',
    'vessels':r'כלי|טביל|הטביל',
    'festivals':r'חנוכה|פסח|פורים|פורימ|סוכה|סוכות|יום טוב|יומ טוב',
    'money':r'כסף|כספ|אבדה|אבידה|ריבית',
}

def spans(text,pattern):
    return [{'text':m.group(),'start':m.start(),'end':m.end()} for m in re.finditer(pattern,text)]

def understand(question):
    clauses=[]
    for match in re.finditer(r'[^?;\n]+',question):
        text=match.group().strip()
        if not text:continue
        actions=[]
        for name,pattern in ACTION_PATTERNS.items():
            for m in re.finditer(pattern,question[match.start():match.end()]):
                begin=match.start()+m.start();end=match.start()+m.end()
                prefix=question[max(match.start(),begin-18):begin]
                actions.append({'kind':name,'text':question[begin:end],'start':begin,'end':end,
                    'negated':bool(re.search(r'(?:לא|בלי|שלא)\s+(?:\S+\s+){0,1}$',prefix)),
                    'occurrence':'reported-past' if m.group().endswith('תי') else 'requested-or-discussed',
                    'interpretation':'linguistic-candidate; not an assumed case fact'})
        clauses.append({'text':text,'start':match.start(),'end':match.end(),'actions':actions})
    q=normalize(question)
    modalities=[{'kind':name,'evidence':spans(question,pat)} for name,pat in (
        ('permission',r'מותר|אסור|אפשר'),('obligation',r'חייב|חייבת|צריך'),
        ('custom',r'מנהג|נוהגים|נוהג'),('stringency',r'חומרה|מחמיר|להחמיר'),
        ('recommendation',r'ראוי|עדיף|טוב לעשות')) if re.search(pat,question)]
    topics=[name for name,pattern in TOPICS.items() if re.search(pattern,q)]
    colloquial=[]
    if ('בשרי' in q and 'שמנ' in q and ('שניצל' in q or 'ציפס' in q)):
        colloquial=['מעמד מאכל שטוגן בשמן ששימש לבשר','המתנה היא סוגיה נפרדת מאיסור תערובת']
    return {'clauses':clauses[:8],'topics':topics,'modalities':modalities,
        'question_kind':'personal-case' if re.search(r'אכלתי|שכחתי|בירכתי|ברכתי|עשיתי|הדלקתי|מצאתי',question) else 'general-or-unspecified',
        'correction':bool(re.search(r'בעצם|תיקון|טעיתי|התכוונתי',question)),
        'followup_cues':spans(question,r'זה היה|כבר סיימתי|לאחר מכן|ואם|בעצם|תיקון'),
        'time_place_spans':spans(question,r'שחרית|מנחה|ערבית|בלילה|ביום|לפני|אחרי|לאחר|בתוך הסעודה|בארץ ישראל|בחוץ לארץ'),
        'colloquial_issue_candidates':colloquial,'scope':'user-language analysis only; no halachic inference',
        'model_proposals_verified':False}
