"""Read a dual-column blessing table; classification is not a case ruling."""
import re
from .hebrew import normalize


FIRST_NAMES={
    'העץ':'בורא פרי העץ','האדמה':'בורא פרי האדמה',
    'שהכל':'שהכל נהיה בדברו','מזונות':'בורא מיני מזונות',
    'המוציא':'המוציא לחם מן הארץ',
}
LAST_NAMES=('נפשות','מעין שלוש','מעין שלש','על המחיה','ברכת המזון','על העץ','על העץ ועל פרי העץ')


def table_row(text):
    match=re.fullmatch(r'([^\n/–—]+)\s*[–—]\s*([^\n/]+)\s*/\s*([^\n/]+)',text.strip().rstrip('.'))
    if not match:return None
    return dict(zip(('food','first_column','last_column'),(v.strip() for v in match.groups())))


def food_subject(question):
    """Only a syntactically explicit food query; no inferred food or stage."""
    # Scope/facts after a question mark are not part of the food's name.
    # Preserve them elsewhere for applicability and the after-blessing guard.
    q=normalize(re.split(r'[?\n]',question,maxsplit=1)[0]).strip()
    match=re.fullmatch(r'(?:מה|איזו)\s+(?:מברכימ|הברכה|ברכה)\s+על\s+(.+)',q)
    if not match:return None
    from .ranking import canonical_query_token
    words=[canonical_query_token(w) for w in match.group(1).split()]
    if words and words[0] in ('אגוז','אגוזי','פרי'):words=words[1:]
    return ' '.join(words) or None


def matching_first_table(question, source):
    subject=food_subject(question)
    row=table_row(source.get('text',''))
    return bool(subject and row and normalize(row['food'])==subject
                and 'לוח ברכות' in source.get('reference',''))


def context_issue(question, evidence):
    q=normalize(question)
    if not ('מברכ' in q or 'ברכה' in q):return None
    if 'אחרונה' in q or 'בורא נפשות' in q or 'על המחיה' in q:
        texts=[normalize(e.get('quote','')) for e in evidence]
        if not any('כזית' in t and ('אכילת פרס' in t or 'אכילה פרס' in t) for t in texts):
            return 'after-blessing quotation lacks explicit quantity and eating-time context'
    tables=[e for e in evidence if table_row(e.get('quote',''))]
    if not tables:return None
    if 'ראשונה' not in q and 'אחרונה' not in q:
        return 'blessing stage unspecified; a two-column table is not a complete case answer'
    if 'אחרונה' in q:
        return 'a table row does not prove after-blessing quantity, timing and case applicability'
    return None

def source_stage_issue(question,text):
    """A first-blessing question cannot be answered by an after-blessing text."""
    q=normalize(question.split('\n')[0]);t=normalize(text)
    if not food_subject(question) or 'אחרונה' in q:return None
    after=any(marker in t for marker in ('ברכה אחרונה','מעינ שלש','מעינ שלוש','מברכ לאחר','לאחריה','בחתימת','חותמ'))
    first=bool(re.search(r'בורא פרי (?:העצ|האדמה)|בפהע|בפהא|ברכה ראשונה|מברכ.{0,30}(?:העצ|האדמה|שהכל|מזונות)',t))
    if after and not first:return 'after-blessing-only source cannot answer a first-blessing query'
    return None


def reading(evidence, sources):
    index={s['source_id']:s for s in sources}
    result=[]
    for e in evidence:
        row=table_row(e.get('quote',''))
        s=index.get(e['source_id'])
        if row and s and 'לוח ברכות' in s.get('reference',''):
            words=normalize(e['quote']).split()
            has_conditions=any(w in ('אם','רק','כאשר','ובלבד','בתנאי','כזית','פרס','דוקא','בלבד')
                               or w.startswith('כש') for w in words)
            # Projection is a bounded column-label reading, not a semantic
            # completeness heuristic. Any extra column wording stays verbatim.
            has_conditions=has_conditions or row['first_column'] not in ('העץ','האדמה','שהכל','מזונות','המוציא')
            has_conditions=has_conditions or row['last_column'] not in LAST_NAMES
            result.append(dict(row,first_blessing_name=FIRST_NAMES.get(row['first_column']),source_id=s['source_id'],reference=s['reference'],
                               status='table-classification-only',has_conditions=has_conditions,
                               after_blessing_case_verified=False))
    return result
