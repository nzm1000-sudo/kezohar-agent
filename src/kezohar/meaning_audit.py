"""Independent, deterministic meaning checks, with explicit unknowns.

No word-similarity score or model self-assessment certifies entailment. Only a
complete, normalized literal unit can receive mechanical restatement support.
Other wording stays an unverified proposal after passing necessary risk checks.
"""
import re
from .hebrew import strip_niqqud

def plain(text):
    return re.sub(r'\s+',' ',re.sub(r'[.,:;!?״“”"׳\'()\[\]{}]', ' ',strip_niqqud(text))).strip()

def audit(statement,evidence,source_context,kind):
    out=plain(statement);context=plain(evidence);full=plain(source_context)
    risks=[]
    # Preserve opinion and uncertainty, even if the quote was cut after its
    # introductory attribution. A disputed interpretation is not a bare fact.
    opinion=r'(?:יש אומרים|יש מפרשים|לדעת|לשיטת|נחלקו|מחלוקת|מסופק|ספק אם|אפשר ש|ייתכן|יתכן)'
    if re.search(opinion,full) and not re.search(opinion+r'|לפי|פירוש|דעה|מציע|סובר|אמר|מפרש',out):
        risks.append('opinion-or-uncertainty-scope-omitted')
    for predicate in ('היה','היו','נכנס','נכנסה','חטא','חטאו','כתב','אמר','עשה','עשו','בירך','ברך'):
        negative=r'(?<![א-ת])(?:לא|אינו|אינה|אין)\s+'+predicate+r'(?![א-ת])'
        # Align the actor as well as the predicate; different actors in a
        # comparison must not be mistaken for a polarity contradiction.
        for m in re.finditer(r'([א-ת]+)\s+'+negative,context):
            if re.search(r'(?<![א-ת])'+re.escape(m[1])+r'\s+'+predicate+r'(?![א-ת])',out):
                risks.append('actor-predicate-polarity-contradiction')
        for m in re.finditer(r'([א-ת]+)\s+'+negative,out):
            if re.search(r'(?<![א-ת])'+re.escape(m[1])+r'\s+'+predicate+r'(?![א-ת])',context):
                risks.append('actor-predicate-polarity-contradiction')
    # Deictic possessives require resolving their antecedent; literal evidence
    # "כהניו" alone cannot establish whose priests they were.
    if re.search(r'כהניו|תלמידיו|בניו|אשתו',context) and re.search(r'(?:כהנים|כהני|תלמידים|תלמידי|בנים|בני|אשת)\s+של\s+',out):
        if out not in context:risks.append('possessive-antecedent-unresolved')
    literal=out==context
    return {'status':'rejected' if risks else 'literal-restatement' if literal else 'unverified-paraphrase',
        'risks':list(dict.fromkeys(risks)),
        'support_kind':'literal' if kind=='quote' else 'normalized-literal-restatement' if literal else 'source-linked-proposal',
        'semantic_entailment_verified':False,
        'checks':['opinion-scope','actor-predicate-polarity','possessive-binding','complete-unit-restatement'],
        'limitations':['free paraphrase entailment is not proved','not a halachic approval']}
