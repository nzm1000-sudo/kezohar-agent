"""Definition requests and editorial search aliases, never canned answers."""
import re
from .hebrew import normalize,strip_niqqud

TERMS=(
    {'id':'nat-bar-nat','aliases':('נט בר נט','נותן טעם בר נותן טעם','נותן טעם בן נותן טעם'),
     'queries':('נותן טעם בר נותן טעם','נט בר נט'),'context':('טעם',),'required_expansion':'נותן טעם בר נותן טעם'},
    {'id':'ben-yomo','aliases':('כלי בן יומו','בן יומו','בת יומא','בת יומה','בני יומן'),
     'queries':('בן יומו דהיינו','בן יומו עשרים וארבע שעות'),'context':('כלי','קדירה','קדרה','סיר','תבשיל')},
)

def definition_request(question):
    q=normalize(question.split('\n')[0])
    match=re.match(r'^(?:מה זה אומר|מה זאת אומרת|מה זה|מהי|מהו|מה פירוש(?: המונח| המושג| הביטוי| המילה)?|מה משמעות(?: המונח| הביטוי)?|מה הכוונה ב)\s+(.+)$',q)
    if not match:return None
    target=re.split(r'\s+(?:בגמרא|בתלמוד|בחסידות|בקבלה|לפי המקורות)(?=\s|$)',match[1],maxsplit=1)[0].strip()
    for term in TERMS:
        if target in [normalize(a) for a in term['aliases']]:return dict(term,target=target,display_target=term['aliases'][0])
    return {'id':None,'target':target,'display_target':target,'aliases':(target,),'queries':(target,),'context':()}

def matches(text,terms):
    text=normalize(text)
    return any(re.search(r'(?<![א-ת])ו?[בכלמשה]?'+re.escape(normalize(t))+r'(?![א-ת])',text) for t in terms)

def focused_followup(question,history):
    """Carry only the explicit subject; prior answers never become evidence."""
    if not history or not re.fullmatch(r'(?:תסביר|הסבר)(?: לי)?(?: יותר)? פשוט(?: יותר)?(?: ותן דוגמה)?[.!? ]*',question.strip()):return None
    previous=next((q for q in reversed(history) if definition_request(q)),None)
    if not previous:return None
    definition=definition_request(previous)
    return 'מה פירוש '+definition['display_target']+'?\nבקשת סגנון בלבד: הסבר פשוט יותר ותן דוגמה קצרה מתוך המקורות. אין להוסיף פסיקה למקרה אישי.'
