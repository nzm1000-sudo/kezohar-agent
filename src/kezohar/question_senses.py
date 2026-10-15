"""Typed query senses before lexical expansion; eligibility is not entailment.

Synonyms stay inside a sense. Different procedures are never synonyms. This
registry can grow without changing retrieval, citation or display consumers.
"""
import re
from .hebrew import normalize

PROCEDURES={
    'ivf':('הפריה חוץ גופית','הפריה חוץ-גופית','הפריה חוץ־גופית','הפריית מבחנה','הפרית מבחנה','ivf'),
    'insemination':('הזרעה מלאכותית','הזרעה תוך רחמית','iui'),
    'sperm-donation':('תרומת זרע','זרע מתורם','זרע של תורם'),
    'egg-donation':('תרומת ביצית','תרומת ביציות','ביצית מתורמת','ביציות מתורמת'),
}
INSUFFICIENT='לא נמצאה במאגר תשובה הלכתית מבוססת לשאלה זו. נדרש בירור נוסף.'
QUESTION='לאיזה טיפול התכוונת — הפריה חוץ־גופית (IVF), הזרעה מלאכותית, תרומת זרע או תרומת ביצית?'
OPTIONS=[{'value':k,'label':v[0]} for k,v in PROCEDURES.items()]+[{'value':'unknown','label':'איני יודע את סוג הטיפול'}]

def contains(text,phrase):
    return bool(re.search(r'(?<![א-תa-z])ו?[בכלמשה]?'+re.escape(normalize(phrase))+r'(?![א-תa-z])',normalize(text),re.I))

def classify(question,procedure=None):
    q=question.split('\n')[0]
    kinds=[k for k,words in PROCEDURES.items() if any(contains(q,w) for w in words)]
    fertility=bool(kinds or re.search(r'(?<![א-ת])ו?[בכלמשה]?(?:הפריה|הפרייה|הפרית|הפריית|פוריות|הזרעה)(?![א-ת])',normalize(q)))
    if not fertility:
        return {'domain':'procreation-commandment' if re.search(r'פרי[יה]*ה? ורבי[יה]*ה?',normalize(q)) else
                'produce-blessing' if contains(q,'פירות הארץ') and any(t in normalize(q) for t in ('מברכ','ברכה','ברכת')) else 'other', 'procedures':[],'ambiguous':False}
    conflict=bool(procedure and procedure!='unknown' and kinds and procedure not in kinds)
    if not kinds and procedure in PROCEDURES:kinds=[procedure]
    return {'domain':'fertility-treatment','procedures':kinds,'ambiguous':not kinds or conflict,
            'conflict':conflict,'basis':'explicit procedure terms; no ruling or donor assumptions'}

def relevance_issue(question,text):
    sense=classify(question)
    if sense['domain']=='procreation-commandment':
        if not re.search(r'פרי[יה]*ה? ורבי[יה]*ה?|פרו ורבו',normalize(text)):
            return 'procreation commandment absent; fertility or fruit words are not equivalent'
    if sense['domain']=='produce-blessing':
        if not (re.search(r'פרי|פירות|ירק|אדמה',normalize(text)) and re.search(r'מברכ|ברכת|בורא|העצ|האדמה',normalize(text))):
            return 'produce blessing absent; procreation terminology is not a substitute'
    if sense['domain']!='fertility-treatment':return None
    if sense['ambiguous']:return 'procedure meaning unresolved; lexical overlap cannot establish relevance'
    # All requested axes must occur in the actual evidence, not just a title.
    for kind in sense['procedures']:
        if not any(contains(text,term) for term in PROCEDURES[kind]):return 'requested procedure absent: '+kind
    return None

def clarification(question,procedure=None):
    sense=classify(question,procedure)
    if sense['domain']!='fertility-treatment' or not sense['ambiguous']:return None
    unknown=procedure=='unknown'
    return {'answer':INSUFFICIENT if unknown else QUESTION,'sources':[],
        'verdict':'insufficient_context' if unknown else 'needs_clarification','mode':'clarification',
        'clarifications':[] if unknown else [{'field':'fertility_procedure','question':QUESTION,'options':OPTIONS}],
        'question_sense':sense,'halachic_verified':False,
        'verification':{'verdict':'insufficient_context','checks':{'quotation_integrity':'not-applied',
            'source_relevance':'not-established','halachic_conclusion':'not-established'}},
        'verification_layers':{'quotation_integrity':'not-applied','source_relevance':'not-established',
            'halachic_conclusion':'not-established','human_review':'not-performed','halachic_verified':False}}
