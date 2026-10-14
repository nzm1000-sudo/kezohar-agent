"""Identity grammar and orthography are search aids, never asserted facts."""
import re,unicodedata
from .hebrew import strip_niqqud

SPELLINGS={'חופני':'חפני','פינחס':'פנחס'}

def name(value):
    value=strip_niqqud(unicodedata.normalize('NFKD',value)).strip()
    return SPELLINGS.get(value,value)

def qualified(value):
    m=re.fullmatch(r'(.+?)\s+בן\s+(.+)',value.strip())
    return (name(m[1]),name(m[2])) if m else (name(value),None)

def identity_request(question):
    q=strip_niqqud(question.split('\n')[0]).strip().rstrip('?')
    children=re.match(r'מי (?:היו )?(?:בניו|בני|בנותיו|בנות)\s+(?:של\s+)?(.+)',q)
    if children:
        parent=re.sub(r'\s+(?:הכהן|המלך|אבינו|רבנו)$','',children[1])
        return {'identity_kind':'children','parent':name(parent),'subjects':[],'unresolved':[]}
    who=re.match(r'מי (?:היו|היה|הייתה|היתה|זה|אלה)\s+(.+)',q)
    if not who:return None
    # Relationship/book questions keep their existing dedicated routes.
    if re.search(r'אביו|אמו|אשתו|אבא|אמא|מחבר|רבו|אב של|אם של',who[1]):return None
    subjects=[qualified(s) for s in re.split(r'\s+ו(?=[א-ת])|\s+ו\s+',who[1])]
    return {'identity_kind':'people','subjects':[{'name':n,'father_qualifier':f} for n,f in subjects],
            'parent':None,'unresolved':[]}
