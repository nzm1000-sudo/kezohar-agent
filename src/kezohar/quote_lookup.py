"""'מי אמר / איפה כתוב / מה המקור של <ביטוי>': exact phrase search in the libraries.

A quoted phrase is located, not interpreted: the answer shows where the words
appear (Tanakh first), with the preceding verse as context for who speaks.
The speaker is never asserted from the model.
"""
import re
import sqlite3
import json
from . import hebrew

ASK = re.compile(r'^\s*(?:מי\s+אמר|מי\s+כתב|איפה\s+כתוב|היכן\s+כתוב|איפה\s+מופיע|היכן\s+מופיע|מה\s+המקור\s+של|מאיפה'
                 r'(?:\s+(?:הביטוי|המשפט|הפסוק))?|מקור\s+(?:הביטוי|המשפט|הפסוק))\s*[:\-]?\s*(.+?)\s*\??\s*$')
TANAKH = ('בראשית', 'שמות', 'ויקרא', 'במדבר', 'דברים', 'יהושע', 'שופטים', 'שמואל א', 'שמואל ב', 'מלכים א', 'מלכים ב',
          'ישעיהו', 'ירמיהו', 'יחזקאל', 'הושע', 'יואל', 'עמוס', 'עובדיה', 'יונה', 'מיכה', 'נחום', 'חבקוק', 'צפניה', 'חגי',
          'זכריה', 'מלאכי', 'תהילים', 'משלי', 'איוב', 'שיר השירים', 'רות', 'איכה', 'קהלת', 'אסתר', 'דניאל', 'עזרא', 'נחמיה',
          'דברי הימים א', 'דברי הימים ב')


def phrase_of(question, display=False):
    m = ASK.match(question.split('\n')[0])
    if not m:
        return None
    phrase = m.group(1).strip().strip('"״\'׳').strip()
    words = hebrew.normalize(phrase).split()
    if not 2 <= len(words) <= 12:
        return None
    return phrase if display else ' '.join(words)


def _rank(source):
    title = source.get('work_title', '')
    return (0 if title in TANAKH else 1 if title.startswith(('משנה ', 'תלמוד')) else 2)


def _hits(path, phrase, limit=40):
    sql = ('SELECT records.payload FROM library_fts JOIN records ON records.rowid=library_fts.rowid '
           'WHERE library_fts MATCH ?')
    match = '"' + phrase.replace('"', '') + '"'
    with sqlite3.connect(str(path.as_uri()) + '?mode=ro', uri=True, timeout=5) as db:
        # The verse itself first: later works quoting it are far more numerous.
        rows = db.execute(sql + " AND json_extract(records.payload,'$.work_title') IN (" + ','.join('?' * len(TANAKH))
                          + ') LIMIT 10', (match,) + TANAKH).fetchall()
        rows += db.execute(sql + ' LIMIT ?', (match, limit)).fetchall()
    out, seen = [], set()
    for (payload,) in rows:
        source = json.loads(payload)
        if source['source_id'] not in seen:
            seen.add(source['source_id']); out.append(source)
    return out


def _skeleton(word):
    """Spelling-tolerant form: no prefix letter, no ו/י after the first letter (השומר ~ השמר ~ ושמר)."""
    word = re.sub(r'^[והבלמשכ](?=..)', '', word)
    return word[:1] + re.sub(r'[וי]', '', word[1:])


def contains(normalized_text, phrase):
    want = [_skeleton(w) for w in phrase.split()]
    have = [_skeleton(w) for w in normalized_text.split()]
    return any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))


def _semantic_tanakh(search, question, phrase):
    """Tanakh verses near the phrase in meaning, kept only if the words really appear in sequence."""
    out = []
    for dense in [b for b in getattr(search, 'backends', []) if hasattr(b, 'index')]:
        try:
            hits = dense.search(phrase, top_k=60)
        except Exception:
            continue
        out += [s for s in hits if s.get('work_title') in TANAKH and contains(s.get('normalized_text', ''), phrase)]
    return out


def _previous_verse(library, source):
    m = re.match(r'^(.*פרק (\d+) · פסוק )(\d+)$', source.get('reference', ''))
    if not m or int(m.group(3)) < 2:
        return None
    ref = m.group(1) + str(int(m.group(3)) - 1)
    with sqlite3.connect(str(library.path.as_uri()) + '?mode=ro', uri=True, timeout=5) as db:
        row = db.execute("SELECT payload FROM records WHERE json_extract(payload,'$.work_title')=? "
                         "AND json_extract(payload,'$.reference')=? LIMIT 1", (source.get('work_title'), ref)).fetchone()
    return json.loads(row[0]) if row else None


def lookup(question, search):
    phrase = phrase_of(question)
    if not phrase:
        return None
    from .source_snapshot import admissible
    libraries = [b for b in getattr(search, 'backends', []) if hasattr(b, 'path') and not hasattr(b, 'index')]
    found = []
    for library in libraries:
        try:
            found += [(library, s) for s in _hits(library.path, phrase) if admissible(s)]
        except sqlite3.Error:
            continue
    if not any(_rank(s) == 0 for _, s in found):
        verses = _semantic_tanakh(search, question, phrase)
        library = next((l for l in libraries if 'app-library' in str(l.path)), libraries[0] if libraries else None)
        found = [(library, s) for s in verses if admissible(s)] + found
    if not found:
        return None
    found.sort(key=lambda pair: _rank(pair[1]))
    library, best = found[0]
    lines = [f'הביטוי ״{phrase_of(question, display=True)}״ מופיע ב{best["reference"]}:', '״' + best['text'].strip() + '״']
    sources = [best]
    context = _previous_verse(library, best) if _rank(best) == 0 else None
    if context:
        lines.append(f'ההקשר ({context["reference"]}): ״{context["text"].strip()}״')
        sources.append(context)
    others = [s for _, s in found[1:] if s['reference'] != best['reference']][:3]
    if others:
        lines.append('מופיע גם ב: ' + '; '.join(s['reference'] for s in others))
        sources += others
    return {'verdict': 'fact_supported', 'mode': 'quote-lookup', 'answer': '\n'.join(lines), 'sources': sources,
            'quote_lookup': {'phrase': phrase, 'hits': len(found), 'method': 'exact phrase in local library FTS'},
            'halachic_verified': False, 'human_review': 'not-required-for-location', 'internet_used': False}
