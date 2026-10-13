"""Question type is independent of tradition, authority and claim support."""
import re
from .hebrew import strip_niqqud

PUBLIC_ENTITIES=('משה','עמרם','יוכבד','אהרן','מרים','שמואל','חנה','אלקנה','יעקב','ישראל','אברהם','שרה','יצחק','רבקה','יוסף','דוד','שלמה',
    'רבי מאיר','רבי עקיבא','אלישע בן אבויה','רבי יהודה הלוי','רבי חיים ויטאל','הרמב״ם','הרמבם','הרמב״ן','החיד״א','החידא','רשב״א')
PUBLIC_TOPICS=('כוזרי','משנה תורה','תיקו','משנה','גמרא','תלמוד','תנאים','אמוראים','גאונים','עשר הספירות','ספר הבהיר','מדרש תנחומא','ארץ ישראל')

class QuestionIntentRouter:
    def route(self,question):
        q=strip_niqqud(question.split('\n')[0]).replace('רבינו','רבנו').replace('אבא','אב').replace('אמא','אם')
        q=q.replace('רמב"ם','הרמב״ם').replace('החיד"א','החיד״א').replace('חידא','החיד״א')
        hal=bool(re.search(r'מותר|אסור|חייב|צריך להמתין|מברכ|לברך|מה הדין|מה עושים|הלכה למעשה|שכחתי|יעלה ויבוא',q))
        domains=[]
        if hal:domains.append('halacha')
        if re.search(r'מנהג|נוהגים|נוהגין',q):domains.append('custom')
        if re.search(r'משה|יעקב|שמואל|אברהם|תנ.?ך|פסוק|פרשת|יוכבד|עמרם|דוד המלך',q):domains.append('tanakh')
        if re.search(r'גמרא|תלמוד|תיקו|משנה|תנאים|אמוראים',q):domains.append('talmud')
        if re.search(r'קבלה|ספירות|זוהר|הבהיר|חיים ויטאל',q):domains.append('kabbalah')
        if re.search(r'כוזרי|מחשבת ישראל|חסידות',q):domains.append('jewish-thought')
        if re.search(r'היסטורי|תקופת|גאונים|נחתם|מתי נולד',q):domains.append('history')
        if re.search(r'רבי|רבו|תלמיד|החיד|רמב|מי כתב|מחבר',q):domains.append('people-and-books')
        relation=None
        for pattern,kind in ((r'(?:אביו|אב) של','father'),(r'(?:אמו|אימו|אם) של','mother'),
                             (r'(?:אשתו|אישה) של','wife'),(r'(?:בנו|בן) של','son'),
                             (r'(?:אחיו|אח) של','brother'),(r'(?:רבו|רב) של','teacher'),
                             (r'מי (?:כתב|חיבר)|מחבר','author'),(r'כמה בנים','child-count')):
            if re.search(pattern,q):relation=kind;break
        if relation is None and re.search(r'(?:ומי|מי)\s+הייתה\s+אשתו',q):relation='wife'
        entities=[e for e in PUBLIC_ENTITIES if e in q]
        # Keep public names separate from user-written/unresolved entity strings.
        entity=next((e for e in sorted(entities,key=len,reverse=True)),None)
        if relation in ('father','mother','wife','son','brother','teacher'):
            m=re.search(r'של\s+(.+?)(?:\?|$)',q)
            if m:entity=re.sub(r'\s+(?:רבנו|הנביא|אבינו)$','',m[1].strip())
        if relation=='child-count' and 'יעקב' in q:entity='יעקב'
        kind=('halachic' if hal else 'fact' if relation or re.match(r'מי (?:היה|הייתה|היתה)',q) else
              'interpretation' if re.search(r'מדוע|למה|פירוש|פרשנות|מה ההבדל|הסבר',q) else 'research')
        explicit_deep=bool(re.search(r'עיון מעמיק|מחקר|חקור|לעומק',q))
        knowledge=not hal and bool(relation or domains or entities or any(t in q for t in PUBLIC_TOPICS))
        return {'kind':kind,'domains':list(dict.fromkeys(domains)) or ['unclassified'],
            'engine':'jewish-knowledge' if knowledge else 'halachic',
            'relation':relation,'entity':entity,'public_entities':entities,
            'complexity':'deep' if explicit_deep else 'simple' if kind=='fact' else 'explanation',
            'normalized_question':q,'decision_basis':'question grammar and topic cues; not an asserted fact',
            'halachic_verified':False}
