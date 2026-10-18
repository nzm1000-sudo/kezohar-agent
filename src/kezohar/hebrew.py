"""Hebrew normalization for search only. Original text is never modified."""
import functools
import re
import unicodedata

NIQQUD_RE = re.compile(r'[֑-ׇ]')
FINAL_MAP = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})
GERESH_VARIANTS = ["׳", "״", "׳", "״", "'", '"', "`", "’", "‘", "״"]
PUNCT_RE = re.compile(r'[^\w֐-׿]+', re.UNICODE)
WS_RE = re.compile(r'\s+')

def strip_niqqud(s):
    # The maqaf (U+05BE) sits inside the niqqud range: removing it fused the words ("ישראל־מאיר" -> "ישראלמאיר").
    return NIQQUD_RE.sub("", s.replace("\u05be", " "))

def unify_finals(s):
    return s.translate(FINAL_MAP)

@functools.lru_cache(maxsize=200000)  # a pure function called ~240,000 times an answer, mostly on the same words
def normalize(s):
    """Normalize Hebrew for search: strip niqqud/taamim, unify finals,
    drop geresh variants, lowercase latin, collapse spaces."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    # Maqaf joins words ("שַׁל־נְעָלֶיךָ"); stripping it with the niqqud fused them ("שלנעליכ").
    s = s.replace("־", " ")
    s = strip_niqqud(s)
    s = unify_finals(s)
    for g in GERESH_VARIANTS:
        s = s.replace(g, "")
    s = s.replace(":", " ").replace("-", " ").replace("–", " ").replace("—", " ")
    s = PUNCT_RE.sub(" ", s)
    s = WS_RE.sub(" ", s).strip().lower()
    return s

def tokens(s):
    return normalize(s).split()

def normalize_ref(s):
    """Normalize a reference string (e.g. 'רח:ז') without destroying digits.
    Unifies finals so 'שח:ג' matches, but keeps digits/colons mapped to space."""
    if not s:
        return ""
    s = strip_niqqud(s)
    s = unify_finals(s)
    for g in GERESH_VARIANTS:
        s = s.replace(g, "")
    s = WS_RE.sub(" ", s.replace(":", " ").strip().lower())
    return s
