"""Bounded circumstance intake, not halachic inference or a ruling database."""
from .hebrew import normalize
from .semantic_claims import question_intent

SLOTS = {
    'rice_form': ('באיזה אופן האורז נאכל?', {'raw':'אורז לא מבושל', 'cooked':'אורז מבושל', 'mixed':'אורז בתערובת', 'bread':'פת מאורז'}),
    'prayer_stage': ('באיזה שלב נזכרת שלא אמרת יעלה ויבוא?', {'during':'עדיין באמצע התפילה', 'finished':'סיימתי ועקרתי רגליים', 'after_musaf':'לאחר תפילת מוסף'}),
    'oil_case': ('האם זה אותו שמן ששימש לטיגון הבשר, או שמן חדש?', {'same':'אותו שמן ששימש לטיגון הבשר', 'new_clean':'שמן חדש בכלי נקי', 'unknown':'לא ידוע מה מצב השמן'}),
    'travel_distance': ('האם ידוע מרחק הנסיעה ביחס לפרסה?', {'at_least_parsa':'מרחק הנסיעה לפחות פרסה', 'less_than_parsa':'מרחק הנסיעה פחות מפרסה', 'unknown':'מרחק הנסיעה לא ידוע'}),
    'travel_stage': ('האם כבר התחלת בנסיעה?', {'before':'לפני תחילת הנסיעה', 'started':'לאחר שהתחלתי בנסיעה', 'unknown':'שלב הנסיעה לא ידוע'}),
    'tradition': ('לפי איזו מסורת מבוקש המענה?', {'sephardi':'לפי פסיקת הספרדים', 'ashkenazi':'לפי פסיקת האשכנזים', 'both':'השוואת מסורות'})
}
SLOTS.update({
    'phone_purpose': ('לשם מה מבוקש טלטול הטלפון בשבת?', {'use':'לצורך שימוש בטלפון', 'place':'לצורך מקומו של הטלפון', 'protect':'לשמירת הטלפון מנזק', 'unknown':'מטרת הטלטול לא ידועה'}),
    'water_temperature': ('מה מצב המים שרוצים להוסיף למיחם?', {'boiling':'מים רותחים', 'hot':'מים חמים שאינם רותחים', 'cold':'מים קרים', 'unknown':'מצב המים לא ידוע'})
})


def analyze(question, circumstances=None):
    supplied = {} if circumstances is None else circumstances
    if not isinstance(supplied, dict) or any(k not in SLOTS or not isinstance(v,str) or v not in SLOTS[k][1] for k,v in supplied.items()):
        raise ValueError('circumstances must contain supported slot/value pairs')
    q = normalize(question)
    intent = question_intent(question)
    if 'טלפונ' in q and 'שבת' in q:intent='phone-shabbat'
    if 'מיחמ' in q and any(t in q for t in ('להוסיפ','להכניס')):intent='water-urn'
    facts = {}
    if intent == 'rice':
        if 'כוסס' in q or 'לא מבושל' in q: facts['rice_form']='raw'
        elif 'תערובת' in q or 'מעורב' in q: facts['rice_form']='mixed'
        elif 'פת מאורז' in q: facts['rice_form']='bread'
        elif 'מבושל' in q or 'בישל' in q: facts['rice_form']='cooked'
    if intent == 'yaaleh-shachrit':
        if 'לאחר' in q and 'מוספ' in q: facts['prayer_stage']='after_musaf'
        elif 'עקרתי' in q or 'עקר רגל' in q: facts['prayer_stage']='finished'
        elif 'באמצע' in q or 'עדיינ בתפילה' in q: facts['prayer_stage']='during'
    if intent == 'shared-oil':
        if 'שמנ חדש' in q and 'נקי' in q: facts['oil_case']='new_clean'
        elif 'אותו שמנ' in q or 'שמנ שבו' in q: facts['oil_case']='same'
    if intent == 'travel':
        if 'פחות מפרסה' in q: facts['travel_distance']='less_than_parsa'
        elif 'לפחות פרסה' in q or 'פרסה לפחות' in q: facts['travel_distance']='at_least_parsa'
        if 'לפני תחילת' in q: facts['travel_stage']='before'
        elif 'התחלתי' in q or 'כבר יצאתי' in q: facts['travel_stage']='started'
    if intent=='phone-shabbat':
        if 'לצורכ מקומו' in q:facts['phone_purpose']='place'
        elif 'לשמירת' in q or 'מנזק' in q:facts['phone_purpose']='protect'
        elif 'לצורכ שימוש' in q:facts['phone_purpose']='use'
    if intent=='water-urn':
        if 'שאינמ רותחימ' in q:facts['water_temperature']='hot'
        elif 'רותחימ' in q:facts['water_temperature']='boiling'
        elif 'קרימ' in q:facts['water_temperature']='cold'
    explicit = ('both' if 'השוואת מסורות' in q or ('אשכנז' in q and 'ספרד' in q) else
                'ashkenazi' if 'אשכנז' in q else 'sephardi')
    facts['tradition']=explicit
    conflicts = [k for k,v in supplied.items() if k in facts and facts[k]!=v
                 and k!='tradition']
    facts.update(supplied)
    requirements = {'rice':['rice_form'], 'yaaleh-shachrit':['prayer_stage'],
                    'shared-oil':['oil_case'], 'travel':['travel_distance','travel_stage'],
                    'phone-shabbat':['phone_purpose'],'water-urn':['water_temperature']}
    missing = [k for k in requirements.get(intent,[]) if k not in facts or facts[k]=='unknown']
    clarification = [{'field':k, 'question':SLOTS[k][0],
                      'options':[{'value':v,'label':label} for v,label in SLOTS[k][1].items()]}
                     for k in list(dict.fromkeys(conflicts+missing))[:2]]
    return {'intent':intent or 'general-halacha', 'circumstances':facts,
            'missing_fields':missing, 'conflicting_fields':conflicts,
            'clarifications':clarification,
            'requires_clarification':bool(missing or conflicts),
            'method':'bounded rules; circumstances are not evidence for a ruling'}


def contextual_question(question, analysis):
    facts = [SLOTS[k][1][v] for k,v in analysis['circumstances'].items() if k!='tradition']
    return question + ('\nנסיבות שמסר המשתמש: '+ '; '.join(facts) if facts else '')


def case_coverage(question, source):
    """Retrieval feature only; never used to approve a claim or a locator."""
    analysis=analyze(question)
    text=normalize(source.get('text',''))
    markers={'raw':('כוסס','לא מבושל'), 'cooked':('מבושל','בשלו'),
             'mixed':('מעורב','תערובת'), 'bread':('פת',),
             'finished':('עקר','סיימ'), 'during':('רצה','מודימ'),
             'after_musaf':('מוספ',), 'same':('אותו שמנ','שמנ שבו'),
             'new_clean':('שמנ חדש',), 'at_least_parsa':('פרסה',),
             'less_than_parsa':('פחות מפרסה',), 'before':('לפני','קודמ'),
             'started':('החזיק','יצא')}
    return sum(any(m in text for m in markers.get(v,()))
               for k,v in analysis['circumstances'].items() if k!='tradition')
