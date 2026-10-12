"""Read a dual-column blessing table; classification is not a case ruling."""
import re
from .hebrew import normalize


FIRST_NAMES={
    'העץ':'בורא פרי העץ','האדמה':'בורא פרי האדמה',
    'שהכל':'שהכל נהיה בדברו','מזונות':'בורא מיני מזונות',
    'המוציא':'המוציא לחם מן הארץ',
}


def table_row(text):
    match=re.fullmatch(r'([^\n/–—]+)\s*[–—]\s*([^\n/]+)\s*/\s*([^\n/]+)',text.strip().rstrip('.'))
    if not match:return None
    return dict(zip(('food','first_column','last_column'),(v.strip() for v in match.groups())))


def context_issue(question, evidence):
    q=normalize(question)
    if not ('מברכ' in q or 'ברכה' in q):return None
    if 'אחרונה' in q:
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
            has_conditions=has_conditions or row['last_column'] not in ('נפשות','מעין שלוש','מעין שלש','על המחיה','ברכת המזון','על העץ')
            result.append(dict(row,first_blessing_name=FIRST_NAMES.get(row['first_column']),source_id=s['source_id'],reference=s['reference'],
                               status='table-classification-only',has_conditions=has_conditions,
                               after_blessing_case_verified=False))
    return result
