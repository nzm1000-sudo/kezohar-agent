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


READ_SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}, 'quote': {'type': 'string'}},
               'required': ['answer', 'quote'], 'additionalProperties': False}
READ_PROMPT = ('לפניך לשון המפרש על הפסוק. ענה על השאלה מה הוא אומר: answer — שניים־שלושה משפטים בעברית פשוטה, רק מה '
               'שכתוב בקטע, בלי להוסיף דבר מידיעתך ובלי לייחס לו דבר שאינו כתוב; quote — העתק מילה במילה את המשפט המרכזי '
               'מן הקטע (עד 40 מילים). אם הקטע אינו עוסק במילים שנשאלו, החזר answer ריק. אל תזכיר "הקטע". JSON בלבד.')


def _read(question, name, reference, passage, timeout):
    """(answer, quote) read from the commentator's words only; the quote must be in the passage word for word."""
    from . import config
    from .llm import _post
    from .web_answer import _plain
    body = {'model': config.llm_model(), 'temperature': 0, 'max_tokens': 500, 'stream': False,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'commentary', 'strict': True, 'schema': READ_SCHEMA}},
            'messages': [{'role': 'system', 'content': READ_PROMPT},
                         {'role': 'user', 'content': f'שאלה: {question}\nהמפרש: {name} ({reference})\n\n{passage}'}]}
    got = json.loads(_post(config.llm_base_url(), '/chat/completions', body, timeout=timeout)['choices'][0]['message']['content'])
    answer, quote = ' '.join(got['answer'].split()), _plain(got['quote'])
    if not answer or len(quote) < 8 or quote not in _plain(passage) or len(answer) > 700:
        return None
    return answer, quote


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
    # The comment's paragraphs on the asked words first (its dibur hamatchil), then the rest. Matching ignores nikud:
    # the Ramban's comment is one vocalized paragraph of 4,250 characters, the asked words near its end.
    plain = lambda t: re.sub(r'[\u0591-\u05C7]', '', t)
    stems = [w[:4] for w in phrase.split() if len(w) > 2]
    on_words = [x for x in segments if sum(stem in plain(x) for stem in stems) >= max(1, len(stems) - 1)]
    text = '\n'.join(on_words + [x for x in segments if x not in on_words])
    # Where the comment speaks of the asked words: the whole phrase, else its rarest word (a word like "בארץ" also opens
    # the Ramban's comment, "ויעבר אברם בארץ"). The reading gets that passage, unvocalized, not the whole long comment.
    words = plain(text)
    at = words.find(phrase)
    if at < 0:
        hits = [words.find(stem) for stem in sorted(stems, key=lambda stem: words.count(stem)) if stem in words]
        at = hits[0] if hits else -1
    window = words[max(0, at - 700):at + 1800] if at > 900 else words[:2500]
    source = {'source_id': 'sefaria:' + reference, 'reference': reference, 'text': window, 'work_title': name}
    try:
        found = _read(question, name, reference, window, timeout)
    except Exception:
        found = None
    if found:
        answer, quote = found
        return {'verdict': 'ok', 'mode': 'summary-with-quote', 'answer': answer + '\n״' + quote + '״ (' + reference + ').',
                'sources': [source], 'halachic_verified': False,
                'bari': {'answer': answer, 'quote': quote, 'cite': reference, 'source': 'library'},
                'commentary_lookup': {'commentator': name, 'verse': verse, 'phrase': phrase}}
    # Not read into an answer: the commentator's own words are shown, never a summary from memory (a model "Ramban"
    # once said the Torah was written after the conquest — nothing he says).
    start = max(0, at - 150) if at >= 0 else 0
    excerpt = ('…' if start else '') + words[start:start + 900].strip() + ('…' if start + 900 < len(words) else '')
    # The commentator does not speak of the asked words (Sforno on 12:6 explains ויעבר אברם only): said so, plainly.
    about = phrase in words or all(stem in words for stem in stems)
    lead = f'זה לשון {name} על הפסוק:' if about else f'{name} אינו מפרש את המילים «{phrase}»; זה לשונו על הפסוק:'
    return {'verdict': 'ok', 'mode': 'source-only', 'answer': f'{lead}\n״{excerpt}״ ({reference}).',
            'sources': [source], 'halachic_verified': False,
            'bari': {'answer': lead, 'quote': excerpt, 'cite': reference, 'source': 'library'},
            'commentary_lookup': {'commentator': name, 'verse': verse, 'phrase': phrase, 'read': False}}
