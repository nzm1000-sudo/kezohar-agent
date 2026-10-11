"""Separate topical eligibility from authority/tradition and evidence support."""
from . import hebrew

STOP = {'מה','מתי','האם','איך','כמה','זמן','על','של','עם','בין','הדין','דין','מותר','אסור',
        'אפשר','צריך','לאכול','ברכה','ברכות','ברכת','מברכים','הלכה','הלכות','מחכים','לגבי'}

STOP = {hebrew.normalize(word) for word in STOP}

def topic_tokens(question):
    return [t for t in hebrew.tokens(question) if t not in STOP and len(t)>1]

def retrieval_query(question):
    terms = topic_tokens(question)
    from .question_understanding import analyze
    intent=analyze(question)['intent']
    # Expand the requested case, never an answer or a predetermined ruling.
    expansions={'travel':['תפילת','הדרך','פרסה','החזיק'],
                'birkat-mazon':['ברכת','המזון','יתעכל','רעב'],
                'tea':['תה','שקית','כלי','שני'],
                'phone-shabbat':['טלפון','מוקצה','טלטול'],
                'water-urn':['מיחם','להוסיף','מים']}
    terms.extend(expansions.get(intent,[]))
    from .discovery import interpret
    for expansion in interpret(question)['expansions']:
        terms.extend(hebrew.tokens(expansion))
    if not terms:
        return question
    if any('חלב' in t for t in terms):
        terms.extend(['חלב','גבינה'])
    # Keep all core case terms before grammatical variants. Disk FTS limits
    # tokens to 50; interleaving six prefixes per word used to hide later topics.
    expanded = list(dict.fromkeys(terms))
    for term in terms:
        expanded.append(term)
        if len(term)>3 and term[0] in 'הובכלמש':
            expanded.append(term[1:])
        if len(term)>=3:
            expanded.extend(prefix+term for prefix in ('ה','ו','ב','ל','מ','וה'))
    return ' '.join(dict.fromkeys(expanded))


def intent_issue(question, source):
    from .semantic_claims import question_intent
    q=question_intent(question);t=hebrew.normalize(source.get('text',''))
    ref=source.get('reference_en','')
    if q=='yaaleh-shachrit':
        if (not any(w in t for w in ('יעלה ויבא','יעלה ויבוא'))
                or not any(w in t for w in ('ראש חודש','ראש חדש','רח '))
                or 'שחרית' not in t
                or not any(w in t for w in ('תפל','תפיל','מודי'))):
            return 'morning Rosh Chodesh prayer case absent'
    if q=='meat-wait' and not ('בשר' in t and any(w in t for w in ('גבינה','חלב'))
            and any(w in t for w in ('שש שעות','להמתינ','המתנה'))):
        return 'explicit waiting after meat absent'
    if q=='birkat-mazon' and not any(w in t for w in ('יתעכל','נתעכל','רעב')):
        return 'meal blessing time requires digestion/hunger context'
    if q=='travel':
        subject=('תפילת הדרכ' in t or 'תפלת הדרכ' in t or 'Orach Chayim.110.' in ref
                 or ('אומר אותה אחר שהחזיק בדרכ' in t))
        if not subject or not any(w in t for w in ('פרסה','החזיק','יצא','יציאה')):
            return 'travel prayer subject and timing not supplied'
    if q=='tea' and not ('תה' in t.split() and 'כלי שני' in t):
        return 'tea in second vessel absent'
    return None


def topic_overlap(text, question):
    """Exact lexical match or one grammatical prefix, never אורז -> אור."""
    terms = topic_tokens(question)
    words = set(hebrew.tokens(text))
    def variants(token):
        result = {token}
        if len(token)>3 and token[0] in 'הובכלמש':
            result.add(token[1:])
        return result
    expanded = set().union(*(variants(w) for w in words)) if words else set()
    overlap = 0
    for term in terms:
        choices = variants(term)
        if any('חלב' in c for c in choices):
            choices.add('גבינה')
        if choices & expanded:
            overlap += 1
    return overlap
