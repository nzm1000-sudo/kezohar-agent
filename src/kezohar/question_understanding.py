"""Bounded circumstance intake, not halachic inference or a ruling database."""
from .hebrew import normalize
from .semantic_claims import question_intent

SLOTS = {
    'immersion_purpose': ('לאיזו טבילה התכוונת?', {'woman_purity':'טבילת אישה לטהרה','vessels':'טבילת כלים','custom':'טבילה של גבר כמנהג','unknown':'סוג הטבילה אינו ידוע'}),
    'rice_form': ('באיזה אופן האורז נאכל?', {'raw':'אורז לא מבושל', 'cooked':'אורז מבושל', 'mixed':'אורז בתערובת', 'bread':'פת מאורז'}),
    'prayer_stage': ('באיזה שלב נזכרת שלא אמרת יעלה ויבוא?', {'during':'עדיין באמצע התפילה', 'finished':'סיימתי ועקרתי רגליים', 'after_musaf':'לאחר תפילת מוסף'}),
    'oil_case': ('האם זה אותו שמן ששימש לטיגון הבשר, או שמן חדש?', {'same':'אותו שמן ששימש לטיגון הבשר', 'new_clean':'שמן חדש בכלי נקי', 'unknown':'לא ידוע מה מצב השמן'}),
    'travel_distance': ('האם ידוע מרחק הנסיעה ביחס לפרסה?', {'at_least_parsa':'מרחק הנסיעה לפחות פרסה', 'less_than_parsa':'מרחק הנסיעה פחות מפרסה', 'unknown':'מרחק הנסיעה לא ידוע'}),
    'travel_stage': ('האם כבר התחלת בנסיעה?', {'before':'לפני תחילת הנסיעה', 'started':'לאחר שהתחלתי בנסיעה', 'unknown':'שלב הנסיעה לא ידוע'}),
    'tradition': ('לפי איזו מסורת מבוקש המענה?', {'sephardi':'לפי פסיקת הספרדים', 'ashkenazi':'לפי פסיקת האשכנזים', 'both':'השוואת מסורות'})
}
SLOTS.update({
    'blessing_stage': ('האם מבוקשת ברכה ראשונה לפני האכילה, או ברכה אחרונה לאחריה?', {'before':'ברכה ראשונה לפני האכילה', 'after':'ברכה אחרונה לאחר האכילה', 'both':'ברכה ראשונה וגם ברכה אחרונה', 'unknown':'לא ידוע איזה שלב מבוקש'}),
    'food_amount': ('מה הכמות שנאכלה ביחס לשיעור כזית?', {'below_kezayit':'נאכל פחות משיעור כזית', 'at_least_kezayit':'נאכל לפחות שיעור כזית', 'unknown':'כמות האכילה לא ידועה'}),
    'eating_time': ('מה משך האכילה ביחס לכדי אכילת פרס?', {'within_pras':'האכילה היתה בתוך כדי אכילת פרס', 'longer':'האכילה נמשכה יותר מכדי אכילת פרס', 'unknown':'משך האכילה לא ידוע'}),
    'prayer_service': ('באיזו תפילה נשכחה ההזכרה?', {'shachrit':'בתפילת שחרית', 'mincha':'בתפילת מנחה', 'arvit':'בתפילת ערבית', 'unknown':'התפילה לא ידועה'}),
    'soup_cooked': ('האם המרק כבר התבשל כל צורכו?', {'fully':'המרק מבושל כל צורכו', 'not_fully':'המרק לא מבושל כל צורכו', 'unknown':'מצב הבישול לא ידוע'}),
    'soup_temperature': ('מה מצב המרק כעת?', {'cold':'המרק קר', 'warm':'המרק עדיין חם', 'unknown':'מצב חום המרק לא ידוע'}),
    'reheating_method': ('כיצד מבוקש לחמם את המרק?', {'hotplate':'על פלטה', 'flame':'על אש', 'other':'באופן אחר; יש לפרט בשאלה', 'unknown':'אופן החימום לא ידוע'}),
    'next_food': ('לאחר הצ׳יפס, האם מבוקש לאכול מאכל חלבי?', {'dairy':'לאחר מכן מבוקש לאכול מאכל חלבי', 'other':'לא מבוקש לאכול מאכל חלבי', 'unknown':'סוג המאכל הבא לא ידוע'}),
    'oil_residue': ('האם נשארו בשמן פירורי בשר או שומן ממשי?', {'present':'נשארו פירורי בשר או שומן ממשי בשמן', 'absent':'לא נשארו שיירי בשר או שומן ממשי בשמן', 'unknown':'מצב שיירי הבשר בשמן לא ידוע'}),
    'phone_purpose': ('לשם מה מבוקש טלטול הטלפון בשבת?', {'use':'לצורך שימוש בטלפון', 'place':'לצורך מקומו של הטלפון', 'protect':'לשמירת הטלפון מנזק', 'unknown':'מטרת הטלטול לא ידועה'}),
    'water_temperature': ('מה מצב המים שרוצים להוסיף למיחם?', {'boiling':'מים רותחים', 'hot':'מים חמים שאינם רותחים', 'cold':'מים קרים', 'unknown':'מצב המים לא ידוע'})
})


def analyze(question, circumstances=None):
    supplied = {} if circumstances is None else circumstances
    if not isinstance(supplied, dict) or any(k not in SLOTS or not isinstance(v,str) or v not in SLOTS[k][1] for k,v in supplied.items()):
        raise ValueError('circumstances must contain supported slot/value pairs')
    q = normalize(question)
    intent = question_intent(question)
    if intent not in ('rice','birkat-mazon') and ('מברכ' in q or 'ברכה' in q) and 'על' in q.split():
        intent='food-blessing'
    if 'יעלה' in q and any(t in q for t in ('ראש חודש', 'ראש חדש')):
        service = supplied.get('prayer_service')
        for word, value in (('שחרית','shachrit'),('מנחה','mincha'),('ערבית','arvit')):
            if word in q:
                service = value
        intent = 'yaaleh-shachrit' if service == 'shachrit' else 'yaaleh-general'
    if 'מרק' in q and 'שבת' in q and any(t in q for t in ('לחממ', 'לחמם', 'חימומ')):
        intent = 'soup-reheat'
    from .discovery import interpret
    discovery=interpret(question)
    if discovery['shared_oil_candidate'] and discovery['waiting_requested']:intent='shared-oil'
    if 'טלפונ' in q and 'שבת' in q:intent='phone-shabbat'
    if 'מיחמ' in q and any(t in q for t in ('להוסיפ','להכניס')):intent='water-urn'
    if any(t in q for t in ('לטבול','טבילה','טובל')) and any(t in q for t in ('ביומ','בלילה')):intent='immersion-time'
    facts = {}
    if intent=='immersion-time':
        if any(w in q for w in ('כלימ','כלי')):facts['immersion_purpose']='vessels'
        elif (any(w in q for w in ('נדה','נידה','טבילת אישה','טבילת אשה'))
              or ('לטהרה' in q and any(w in q for w in ('אישה','אשה')))):
            facts['immersion_purpose']='woman_purity'
        elif 'טבילת גבר' in q:facts['immersion_purpose']='custom'
    if intent=='food-blessing':
        if 'ראשונה' in q: facts['blessing_stage']='before'
        if 'אחרונה' in q: facts['blessing_stage']='both' if 'ראשונה' in q else 'after'
    if intent in ('yaaleh-shachrit','yaaleh-general'):
        for word, value in (('שחרית','shachrit'),('מנחה','mincha'),('ערבית','arvit')):
            if word in q: facts['prayer_service'] = value
        if 'עקרתי' in q or 'עקר רגל' in q or 'סיימתי' in q: facts['prayer_stage']='finished'
        elif 'באמצע' in q: facts['prayer_stage']='during'
    # Soup circumstances come from explicit choices; keyword presence alone
    # cannot distinguish a stated fact from a negation or hypothetical method.
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
        elif 'שמנ של שניצל' in q: facts['oil_case']='same'
        if discovery['dairy_target_explicit']:facts['next_food']='dairy'
        if (('פירור' in q or 'שיירי' in q or 'שומנ' in q)
                and any(t in q for t in ('לא נשארו','בלי פירורי','ללא שיירי'))):facts['oil_residue']='absent'
        elif 'נשארו פירור' in q or 'יש פירורי' in q:facts['oil_residue']='present'
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
    origins={k:'user-question' for k in facts}
    if not any(t in q for t in ('אשכנז','ספרד','השוואת מסורות')):
        origins['tradition']='policy-default'
    facts.update(supplied)
    origins.update({k:'user-supplied-slot' for k in supplied})
    requirements = {'immersion-time':['immersion_purpose'], 'rice':['rice_form'], 'yaaleh-shachrit':['prayer_stage'],
                    'food-blessing':['blessing_stage'],
                    'yaaleh-general':['prayer_service','prayer_stage'],
                    'soup-reheat':['soup_cooked','soup_temperature','reheating_method'],
                    'shared-oil':['oil_case','next_food','oil_residue'], 'travel':['travel_distance','travel_stage'],
                    'phone-shabbat':['phone_purpose'],'water-urn':['water_temperature']}
    if intent=='shared-oil' and (facts.get('oil_case')=='new_clean' or facts.get('next_food')=='other'):
        requirements['shared-oil']=['oil_case','next_food']
    if intent=='food-blessing' and facts.get('blessing_stage') in ('after','both'):
        requirements['food-blessing']+=['food_amount','eating_time']
    missing = [k for k in requirements.get(intent,[]) if k not in facts or facts[k]=='unknown']
    clarification = [{'field':k, 'question':SLOTS[k][0],
                      'options':[{'value':v,'label':label} for v,label in SLOTS[k][1].items()]}
                     for k in list(dict.fromkeys(conflicts+missing))[:2]]
    return {'intent':intent or 'general-halacha', 'circumstances':facts,
            'fact_origins':origins,
            'missing_fields':missing, 'conflicting_fields':conflicts,
            'clarifications':clarification,
            'requires_clarification':bool(missing or conflicts),
            'unable_to_clarify':[k for k in missing if supplied.get(k)=='unknown'],
            'query_hypotheses':discovery['possible_topics'],
            'method':'bounded rules; circumstances are not evidence for a ruling'}


def contextual_question(question, analysis):
    facts = [SLOTS[k][1][v] for k,v in analysis['circumstances'].items() if k!='tradition']
    return question + ('\nנסיבות שמסר המשתמש: '+ '; '.join(facts) if facts else '')


def effective_question(question, analysis):
    """One case/tradition representation for streaming and orchestration."""
    effective=contextual_question(question,analysis)
    if analysis['intent']=='food-blessing' and analysis['circumstances'].get('blessing_stage') in (None,'unknown'):
        # Explicit response scope, not a fact about what the user ate or when.
        # The existing table verifier can approve a first-column classification;
        # it still cannot prove an obligation after eating from that column.
        effective+='\nתחום המענה הכללי: ברכה ראשונה בלבד. אין הנחה בדבר נסיבות האכילה של המשתמש.'
    if analysis['requires_clarification']:
        effective+='\nחסרים פרטים להכרעה אישית: הצג רק מקורות לכללים מותנים בשלמותם. אל תניח נסיבות שלא נמסרו.'

    tradition=analysis['circumstances']['tradition']
    if tradition=='ashkenazi':effective+='\nלפי פסיקת האשכנזים'
    elif tradition=='both':effective+='\nהשוואת מסורות'
    return effective


def case_coverage(question, source):
    """Retrieval feature only; never used to approve a claim or a locator."""
    analysis=analyze(question)
    text=normalize(source.get('text',''))
    markers={'raw':('כוסס','לא מבושל'), 'cooked':('מבושל','בשלו'),
             'mixed':('מעורב','תערובת'), 'bread':('פת',),
             'finished':('עקר','יעקור','סיימ','השלי'), 'during':('רצה','מודימ'),
             'after_musaf':('מוספ',), 'same':('אותו שמנ','שמנ שבו'),
             'new_clean':('שמנ חדש',), 'at_least_parsa':('פרסה',),
             'less_than_parsa':('פחות מפרסה',), 'before':('לפני','קודמ'),
             'started':('החזיק','יצא')}
    return sum(any(m in text for m in markers.get(v,()))
               for k,v in analysis['circumstances'].items() if k!='tradition')


def conflict_confirmation(question, analysis):
    """One source-independent fact confirmation; never halachic evidence.

    Reuses the existing bounded answer-id transport. The id binds the original
    question, field and currently reported value, so stale answers cannot settle
    a different discrepancy. yes/no/unknown all stop repeating that question.
    """
    import hashlib
    if not analysis['conflicting_fields']:return None
    field=analysis['conflicting_fields'][0]
    value=analysis['circumstances'][field]
    key=hashlib.sha256(('case-confirmation-v1|'+normalize(question.split('\n')[0])+'|'+field+'|'+value).encode()).hexdigest()[:32]
    return {'condition_id':key,'field':key,'kind':'case-confirmation',
        'circumstance_field':field,'reported_slot_value':value,
        'question':'הפרט שמסרת כעת הוא ״'+SLOTS[field][1][value]+'״, והוא שונה מהנוסח בשאלה. האם הוא מחליף את הפרט הקודם?',
        'options':[{'value':'yes','label':'כן, הפרט האחרון מחליף את הקודם'},
                   {'value':'no','label':'לא; הפרטים עדיין טעונים בירור'},
                   {'value':'unknown','label':'לא ידוע לי'}]}
