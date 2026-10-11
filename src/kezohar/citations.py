"""Citation verification: Validity / Relevance / Support are separate."""
import re
import json
from . import hebrew
from .source_snapshot import unique_sources, complete_quote

REF_PATTERNS = [
    re.compile(r'([֐-׿\s"\']+?),\s*([֐-׿\s]+?)\s+([^\s:;()]+)\s*:\s*([^\s,;()]+)'),
    re.compile(r'\(?\s*שולחן ערוך\s*,?\s*([^,;()]*?)\s+([^\s:;()]+)\s*:\s*([^\s,;()]+)\s*\)?'),
]

OUT_OF_SCOPE_PAT = re.compile(r'(מזג האוויר|שיר אהבה|מזג אוויר|שיר)')

def extract_refs(answer):
    """Extract (work, section, siman, seif)-ish tuples from answer text."""
    refs = []
    # generic: look for parenthesized refs containing ':' e.g. (שולחן ערוך, אורח חיים רח:ז)
    for m in re.finditer(r'\(([^()]{2,120}:\s*[^()]{1,20})\)', answer):
        refs.append(m.group(1).strip())
    # bare refs like שולחן ערוך ... רח:ז without parens
    for m in re.finditer(r'שולחן ערוך[^()\n]{0,60}?[^\s:;()]+\s*:\s*[^\s,;()]+', answer):
        cand = m.group(0).strip()
        if cand not in refs:
            refs.append(cand)
    return refs

def check_validity(cited_ref, retrieved):
    """Validity: cited ref must match a retrieved source id/reference exactly (normalized)."""
    cnorm = hebrew.normalize_ref(cited_ref)
    for r in retrieved:
        for cand in (r.get("reference", ""), r.get("reference_en", ""), r.get("work_title", "") + " " + r.get("reference", "")):
            if not cand:
                continue
            if hebrew.normalize_ref(cand) == cnorm:
                return True, r
    return False, None

def _stem(t):
    """Light Hebrew prefix stripping for relevance matching (ה/ו/ב/כ/ל/מ/ש)."""
    for _ in range(2):
        if len(t) > 3 and t[0] in ("ה", "ו", "ב", "כ", "ל", "מ", "ש"):
            t = t[1:]
        else:
            break
    return t

def _tok_match(a, b):
    if a == b:
        return True
    sa, sb = _stem(a), _stem(b)
    if sa == sb and len(sa) >= 3:
        return True
    # substring containment for inflected forms (מברכים/מברך, האורז/אורז)
    if len(sa) >= 4 and len(sb) >= 4 and (sa in sb or sb in sa):
        return True
    if len(sa) >= 3 and len(sb) >= 3 and (sa.startswith(sb) or sb.startswith(sa)):
        return True
    return False

def check_relevance(source_text, question, min_overlap=1):
    """Relevance: token overlap between question and source (normalized).

    Uses light prefix-stripping so 'האורז' matches 'אורז' and
    'מברכים' matches 'מברך'. Exact matching would reject valid sources.
    """
    qt = [t for t in hebrew.tokens(question)]
    st = [t for t in hebrew.tokens(source_text)]
    # drop tiny stopwords
    stop = {"מה", "מתי", "מותר", "איך", "האם", "על", "עם", "בין", "של", "את", "זה", "זו"}
    qt = [t for t in qt if t not in stop and len(t) > 1]
    stset = set(st)
    overlap = 0
    for q in qt:
        if any(_tok_match(q, s) for s in stset):
            overlap += 1
    return overlap >= min_overlap, overlap

def verify_answer(question, answer, retrieved):
    """Returns dict: validity / relevance / support + verdict.

    verdicts: ok | no_source | invalid_citation | irrelevant | unsupported | out_of_scope
    """
    if OUT_OF_SCOPE_PAT.search(question) or OUT_OF_SCOPE_PAT.search(answer):
        return {"verdict": "out_of_scope", "details": "out of scope question"}
    refs = extract_refs(answer)
    says_no_source = "אין לי מקור" in answer
    if not refs:
        if says_no_source:
            return {"verdict": "no_source", "details": "admits no source", "refs": []}
        # no citation at all for halachic answer -> unsupported
        return {"verdict": "unsupported", "details": "no citation found", "refs": []}
    results = []
    any_valid, any_relevant = False, False
    for ref in refs:
        valid, match = check_validity(ref, retrieved)
        rel, overlap = (False, 0)
        if match:
            rel, overlap = check_relevance(match.get("text", ""), question)
        results.append({"ref": ref, "valid": valid, "relevant": rel, "overlap": overlap})
        any_valid = any_valid or valid
        any_relevant = any_relevant or rel
    if not all(r["valid"] for r in results):
        return {"verdict": "invalid_citation", "details": "cited ref not in retrieved", "refs": results}
    if not any_relevant:
        return {"verdict": "irrelevant", "details": "source does not match question", "refs": results}
    return {"verdict": "ok", "details": "citation valid and relevant", "refs": results}


def verify_extractive_answer(answer, retrieved):
    """Conservative support verification: every claim must be an exact quotation.

    Relevance/validity alone cannot prove entailment. Free paraphrases are rejected
    by this web-RAG guard, until a validated semantic verifier is available.
    """
    pattern = re.compile(r'[״"]([^״"]+)[״"]\s*\(([^()]+)\)')
    matches = list(pattern.finditer(answer))
    if not matches:
        return {"verdict":"unsupported", "support":"no exact quoted evidence"}
    remainder = pattern.sub('', answer)
    if remainder.strip(' \n\t.:;!?־–—'):
        return {"verdict":"unsupported", "support":"unverified prose outside quotations"}
    try: unique_sources(retrieved)
    except ValueError: return {'verdict':'invalid_citation', 'support':'ambiguous source identity'}
    evidence = []
    for match in matches:
        quote, ref = match.groups()
        matching = [s for s in retrieved if check_validity(ref,[s])[0]]
        if not matching:
            return {"verdict":"invalid_citation"}
        try:
            matches = unique_sources(matching)
        except ValueError:
            return {'verdict':'invalid_citation', 'support':'ambiguous source identity'}
        if len(matches)!=1:
            return {'verdict':'invalid_citation', 'support':'ambiguous reference'}
        source = next((s for s in matching if complete_quote(quote.strip(),s)),None)
        if source is None:
            return {"verdict":"unsupported", "support":"quote not present in cited excerpt"}
        evidence.append({"source_id":source['source_id'], "quote":quote})
    return {"verdict":"ok", "support":"exact-extract-only", "evidence":evidence}


def verify_source_id_answer(answer, retrieved):
    """Strict JSON quotation protocol. Render references only from stored metadata.

    No model-authored claims, locators or authors are accepted. Exact text support
    is unchanged; structured quoting also handles internal Hebrew abbreviations.
    """
    def unique_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('duplicate JSON key')
            obj[key] = value
        return obj
    try:
        payload = json.loads(answer, object_pairs_hook=unique_pairs)
    except (ValueError, TypeError):
        return {'verdict': 'unsupported', 'support': 'invalid quotation JSON'}
    if payload == {'status': 'no_source'}:
        return {'verdict': 'no_source', 'support': 'no claim', 'rendered_answer': 'אין לי מקור לכך.'}
    selection=False
    if isinstance(payload,dict) and set(payload)=={'selected_sources'}:
        ids=payload['selected_sources']
        if (not isinstance(ids,list) or not 1<=len(ids)<=2
                or not all(isinstance(sid,str) and sid.strip()==sid and sid for sid in ids)
                or len(set(ids))!=len(ids)):
            return {'verdict':'unsupported','support':'one or two distinct source ids required'}
        try: index=unique_sources(retrieved)
        except ValueError:return {'verdict':'invalid_citation','support':'ambiguous source id'}
        if any(sid not in index for sid in ids):
            return {'verdict':'invalid_citation','support':'selected source not retrieved'}
        # Server-authored literal copies only. This protocol approves no model
        # wording and never truncates a source or manufactures an evidence unit.
        payload={'quotes':[{'source_id':sid,'quote':index[sid].get('text','').strip()} for sid in ids]}
        selection=True
    if not isinstance(payload, dict) or set(payload) != {'quotes'}:
        return {'verdict': 'unsupported', 'support': 'unexpected claims or fields'}
    quotes = payload['quotes']
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 5:
        return {'verdict': 'unsupported', 'support': 'one to five exact quotes required'}
    try: index = unique_sources(retrieved)
    except ValueError: return {'verdict': 'invalid_citation', 'support': 'ambiguous source id'}
    evidence, rendered = [], []
    for item in quotes:
        if (not isinstance(item, dict) or set(item) != {'source_id', 'quote'}
                or not all(isinstance(v, str) for v in item.values())):
            return {'verdict': 'unsupported', 'support': 'unexpected quote fields'}
        source = index.get(item['source_id'])
        if not source or not source.get('reference'):
            return {'verdict': 'invalid_citation', 'support': 'source id or stored locator absent'}
        quote = item['quote']
        if quote != quote.strip() or not complete_quote(quote,source):
            return {'verdict': 'unsupported', 'support': 'quote not present in cited excerpt'}
        evidence.append({'source_id': item['source_id'], 'quote': quote})
        rendered.append('״' + quote + '״ (' + source['reference'] + ').')
    return {'verdict': 'ok', 'support': 'source-selection-whole-unit-reading' if selection else 'exact-extract-only', 'evidence': evidence,
            'rendered_answer': '\n'.join(rendered), 'human_review': 'required',
            'halachic_verified': False}
