"""'מה אומר <מפרש> על <פסוק>': the commentator's own words on that verse, read before anything is said (owner, 2026-10-18).

"מה אומר האבן עזרא על «והכנעני אז בארץ»" was answered from the model's knowledge ("ידע כללי · ללא מקור") and missed
what Ibn Ezra writes ("יש לו סוד והמשכיל ידום"). Here the verse is found by its words (Sefaria's exact search in the
Tanakh), the commentator's comment on that verse is fetched in its Hebrew edition, and the answer is read from it with
a verbatim quotation (web_answer.read_and_answer). Nothing is answered when the verse or the comment is not found.
Only the verse's words go out (the question's own subject words, owner decision 2026-10-15).
"""
import json
import re
import urllib.parse
import urllib.request

# Hebrew names (as people write them) → how Sefaria names the comment on a verse ({book} {c}:{v} filled in).
COMMENTATORS = [
    (r'רש"?י|רש״י|רשי', 'רש״י', 'Rashi on {book} {c}:{v}'),
    (r'רמב"?ן|רמב״ן|נחמנידס', 'רמב״ן', 'Ramban on {book} {c}:{v}'),
    (r'(?:ה)?אבן\s*עזרא|ראב"?ע|ראב״ע', 'אבן עזרא', 'Ibn Ezra on {book} {c}:{v}'),
    (r'(?:ה)?ספורנו', 'ספורנו', 'Sforno on {book} {c}:{v}'),
    (r'(?:ה)?אור\s*החיים', 'אור החיים', 'Or HaChaim on {book} {c}:{v}'),
    (r'(?:ה)?כלי\s*יקר', 'כלי יקר', 'Kli Yakar on {book} {c}:{v}'),
    (r'רשב"?ם|רשב״ם', 'רשב״ם', 'Rashbam on {book} {c}:{v}'),
    (r'(?:ה)?חזקוני', 'חזקוני', 'Chizkuni, {book} {c}:{v}'),
    (r'(?:ה)?בעל\s*הטורים', 'בעל הטורים', "Ba'al HaTurim on {book} {c}:{v}"),
    (r'(?:ה)?דעת\s*זקנים', 'דעת זקנים', "Da'at Zekenim on {book} {c}:{v}"),
    (r'רבינו\s*בחיי|רבנו\s*בחיי', 'רבינו בחיי', 'Rabbeinu Bahya, {book} {c}:{v}'),
    (r'(?:ה)?העמק\s*דבר|(?:ה)?נצי"?ב', 'העמק דבר', 'Haamek Davar on {book} {c}:{v}'),
    (r'(?:ה)?תורה\s*תמימה', 'תורה תמימה', 'Torah Temimah on Torah, {book} {c}:{v}'),
    (r'(?:ה)?מלבי"?ם|מלבי״ם', 'מלבי״ם', 'Malbim on {book} {c}:{v}'),
    (r'רד"?ק|רד״ק', 'רד״ק', 'Radak on {book} {c}:{v}'),
    (r'(?:ה)?מצודת\s*דוד', 'מצודת דוד', 'Metzudat David on {book} {c}:{v}'),
    (r'(?:ה)?אונקלוס|(?:ה)?תרגום\s*אונקלוס', 'אונקלוס', 'Onkelos {book} {c}:{v}'),
]
ASKS = re.compile(r'(?:מה|מהו|מה\s+בדיוק)\s+(?:אומר|כותב|מפרש|מסביר|פירש|פירוש)|(?:פירוש|דברי|לפי|לדעת|איך\s+מפרש)')
QUOTED = re.compile(r'[«"״“]([^«»"״“”]{4,80})[»"״”]')
SEFARIA = 'https://www.sefaria.org/api/'
UA = {'User-Agent': 'KezoharAgent/1.0 (Jewish learning app)', 'Content-Type': 'application/json'}


def asked(question):
    """(Hebrew name, Sefaria pattern, the verse's words) when the question asks what a commentator says on a verse."""
    first = question.split('\n')[0]
    if not ASKS.search(first):
        return None
    for pattern, name, ref in COMMENTATORS:
        # "הרמב"ן", "והאבן עזרא", "לרש"י", "שהספורנו": the name may carry a prefix letter.
        named = r'(?<![א-ת])(?:[והלשב]|וה|שה|לה)?(?:' + pattern + r')(?![א-ת])'
        if not re.search(named, first):
            continue
        # The name is taken out first: its own quotation marks (רש"י, רמב"ן) are not the verse's.
        rest = re.sub(named, ' ', first)
        quoted = QUOTED.search(rest)
        phrase = quoted.group(1) if quoted else None
        if not phrase:
            rest = re.sub(r'^\s*(?:ו?מה\s+(?:בדיוק\s+)?(?:אומר|כותב|מפרש|מסביר)|ו?איך\s+מפרש|פירוש|דברי|לפי|לדעת)\s*', '', rest)
            rest = re.sub(r'^\s*(?:את\s+)?(?:על\s+)?(?:ה?פסוק|המילים|הביטוי)?\s*', '', rest)
            phrase = rest.strip(' ?:.,')
        words = re.findall(r'[א-ת]+', phrase or '')
        if 2 <= len(words) <= 14:
            return name, ref, ' '.join(words)
    return None


def _json(url, body=None, timeout=12):
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def verse_of(phrase):
    """'Genesis 12:6' for the verse holding these words (Sefaria's exact search in the Tanakh), or None."""
    data = _json(SEFARIA + 'search-wrapper', {'query': phrase, 'type': 'text', 'field': 'exact', 'source_proj': True,
                                              'filters': ['Tanakh'], 'filter_fields': ['path'], 'size': 5})
    for hit in data.get('hits', {}).get('hits', []):
        ref = hit.get('_source', {}).get('ref', '')
        if re.match(r'^[A-Za-z ]+ \d+:\d+$', ref):
            return ref
    return None


def comment(pattern, verse):
    """(Hebrew reference, [segments]) of the commentator's comment on the verse, or None."""
    book, cv = verse.rsplit(' ', 1)
    c, v = cv.split(':')
    ref = pattern.format(book=book, c=c, v=v)
    data = _json(SEFARIA + 'v3/texts/' + urllib.parse.quote(ref) + '?version=hebrew&return_format=text_only')
    version = (data.get('versions') or [{}])[0]
    text = version.get('text')
    segments = [s for s in (text if isinstance(text, list) else [text]) if isinstance(s, str) and s.strip()]
    return (data.get('heRef') or ref, segments) if segments else None


def lookup(question, timeout=35):
    found = asked(question)
    if not found:
        return None
    name, pattern, phrase = found
    try:
        verse = verse_of(phrase)
        got = comment(pattern, verse) if verse else None
    except Exception:
        return None
    if not got:
        return None
    reference, segments = got
    # The comment's paragraphs on the asked words first (its dibur hamatchil), then the rest of the comment.
    stems = [w[:4] for w in phrase.split() if len(w) > 2]
    on_words = [s for s in segments if any(stem in s[:40] for stem in stems)]
    text = '\n'.join(on_words + [s for s in segments if s not in on_words])
    source = {'source_id': 'sefaria:' + reference, 'reference': reference, 'text': text, 'work_title': name}
    from .web_answer import read_and_answer
    found = read_and_answer(question, [source], timeout=timeout, chars=2500)
    if not found:
        return None
    answer, quote, chosen, _ = found
    return {'verdict': 'ok', 'mode': 'summary-with-quote', 'answer': answer + '\n״' + quote + '״ (' + reference + ').',
            'sources': [source], 'halachic_verified': False,
            'bari': {'answer': answer, 'quote': quote, 'cite': reference, 'source': 'library'},
            'commentary_lookup': {'commentator': name, 'verse': verse, 'phrase': phrase}}
