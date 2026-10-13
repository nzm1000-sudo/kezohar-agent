"""Question type is independent of tradition, authority and claim support."""
import re
from .hebrew import strip_niqqud

PUBLIC_ENTITIES=('משה','עמרם','יוכבד','אהרן','מרים','שמואל','חנה','אלקנה','יעקב','ישראל','אברהם','שרה','יצחק','רבקה','יוסף','דוד','שלמה',
    'רבי מאיר','רבי עקיבא','אלישע בן אבויה','רבי יהודה הלוי','רבי חיים ויטאל','הרמב״ם','הרמבם','הרמב״ן','החיד״א','החידא','רשב״א')
PUBLIC_TOPICS=('כוזרי','משנה תורה','תיקו','משנה','גמרא','תלמוד','תנאים','אמוראים','גאונים','עשר הספירות','ספר הבהיר','מדרש תנחומא','ארץ ישראל')

class QuestionIntentRouter:
    def route(self,question):
        q=strip_niqqud(question.split('\n')[0]).replace('רבינו','רבנו').replace('אבא','אב').replace('אמא','אם')
        q=q.replace('רמב"ם','הרמב״ם').replace('החיד"א','החיד״א')
        q=re.sub(r'\bה?חידא\b','החיד״א',q)
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
        corrections=[]
        if entity and entity not in PUBLIC_ENTITIES and any(cue in q for cue in ('רבנו','הנביא','אבינו')):
            def one_edit(a,b):
                if abs(len(a)-len(b))>1:return False
                if len(a)==len(b):return sum(x!=y for x,y in zip(a,b))==1
                if len(a)>len(b):a,b=b,a
                return any(b[:i]+b[i+1:]==a for i in range(len(b)))
            candidates=[name for name in PUBLIC_ENTITIES if ' ' not in name and one_edit(entity,name)]
            if len(candidates)==1:
                corrections=[{'written':entity,'canonical':candidates[0],'basis':'unique one-edit public name with explicit biblical title; search aid only'}]
                q=q.replace(entity,candidates[0]);entity=candidates[0]
                entities=list(dict.fromkeys(entities+[entity]))
        kind=('halachic' if hal else 'fact' if relation or re.match(r'מי (?:היה|הייתה|היתה)',q) else
              'interpretation' if re.search(r'מדוע|למה|פירוש|פרשנות|מה ההבדל|הסבר',q) else 'research')
        explicit_deep=bool(re.search(r'עיון מעמיק|מחקר|חקור|לעומק',q))
        knowledge=not hal and bool(relation or domains or entities or any(t in q for t in PUBLIC_TOPICS))
        from .fastpath import is_out_of_scope,is_fast_question
        if is_out_of_scope(question):knowledge=False
        if is_fast_question(question) and not relation and kind!='interpretation':knowledge=False
        return {'kind':kind,'domains':list(dict.fromkeys(domains)) or ['unclassified'],
            'engine':'jewish-knowledge' if knowledge else 'halachic',
            'relation':relation,'entity':entity,'public_entities':entities,
            'complexity':'deep' if explicit_deep else 'simple' if kind=='fact' else 'explanation',
            'normalized_question':q,'decision_basis':'question grammar and topic cues; not an asserted fact',
            'export_allowed':not bool(re.search(r'אבא שלי|אמא שלי|אבי שלי|משפחה שלי|קוראים לי|שמי |הטלפון שלי|מספר זהות',q)),
            'spelling_hints':corrections,
            'halachic_verified':False}
