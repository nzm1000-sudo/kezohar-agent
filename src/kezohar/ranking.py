"""Separate topical eligibility from authority/tradition and evidence support."""
from . import hebrew

STOP = {'מה','מתי','האם','איך','כמה','זמן','על','של','עם','בין','הדין','דין','מותר','אסור',
        'אפשר','צריך','לאכול','ברכה','ברכות','ברכת','מברכים','הלכה','הלכות','מחכים','לגבי'}

STOP = {hebrew.normalize(word) for word in STOP}

def topic_tokens(question):
    return [t for t in hebrew.tokens(question) if t not in STOP and len(t)>1]

def retrieval_query(question):
    terms = topic_tokens(question)
    if not terms:
        return question
    if any('חלב' in t for t in terms):
        terms.extend(['חלב','גבינה'])
    expanded = []
    for term in terms:
        expanded.append(term)
        if len(term)>3 and term[0] in 'הובכלמש':
            expanded.append(term[1:])
        if len(term)>=3:
            expanded.extend(prefix+term for prefix in ('ה','ו','ב','ל','מ','וה'))
    return ' '.join(dict.fromkeys(expanded))


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
