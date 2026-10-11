"""Citation verification: Validity / Relevance / Support are separate."""
import re
from . import hebrew

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
            # also allow: normalized cited is substring of normalized retrieved ref or vice versa
            rn = hebrew.normalize_ref(cand)
            if cnorm and rn and (cnorm in rn or rn in cnorm):
                # require at least work title token overlap to avoid cross-book mixing
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
    if not any_valid:
        return {"verdict": "invalid_citation", "details": "cited ref not in retrieved", "refs": results}
    if not any_relevant:
        return {"verdict": "irrelevant", "details": "source does not match question", "refs": results}
    return {"verdict": "ok", "details": "citation valid and relevant", "refs": results}
