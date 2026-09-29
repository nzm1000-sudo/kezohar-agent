"""Fetch fixed Shulchan Aruch passages from Sefaria for the benchmark.

These simulate what the search service will return in Phase 2, so every model
answers from the same real text. Output: bench/contexts.json (committed).
"""
import json, re, urllib.parse, urllib.request
from pathlib import Path

OC, YD = "Shulchan Arukh, Orach Chayim", "Shulchan Arukh, Yoreh De'ah"
HE = {OC: "שולחן ערוך, אורח חיים", YD: "שולחן ערוך, יורה דעה"}

# question number -> list of (book, siman, seif). Chosen as the closest seif;
# the user reviews relevance. Questions without an entry get no sources.
REFS = {
    1: [(OC, 208, 7)],
    2: [(YD, 87, 3)],
    5: [(OC, 422, 1)],
    6: [(OC, 426, 3)],
    7: [(OC, 503, 1)],
    8: [(YD, 89, 1)],
    9: [(OC, 184, 5)],
    10: [(OC, 422, 2)],
    11: [(OC, 676, 1), (OC, 676, 5)],
    14: [(OC, 202, 7), (OC, 204, 1)],
    15: [(OC, 308, 3)],
    16: [(OC, 489, 8)],
    20: [(OC, 110, 7)],
}

def clean(t):
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()

def fetch(book, siman, seif):
    ref = f"{book}.{siman}.{seif}"
    url = "https://www.sefaria.org/api/v3/texts/" + urllib.parse.quote(ref) + "?version=hebrew"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "kezohar-bench"}), timeout=20) as r:
        d = json.load(r)
    v = d["versions"][0]
    text = v["text"]
    if isinstance(text, list):
        text = " ".join(text)
    return {
        "ref": ref,
        "he_ref": f"{HE[book]} {heb_num(siman)}:{heb_num(seif)}",
        "version": v.get("versionTitle"),
        "license": v.get("license"),
        "text": clean(text),
    }

def heb_num(n):
    ones = "אבגדהוזחט"; tens = "יכלמנסעפצ"; hund = "קרשת"
    s = ""
    while n >= 400: s += "ת"; n -= 400
    if n >= 100: s += hund[n // 100 - 1]; n %= 100
    if n in (15, 16): return s + ("טו" if n == 15 else "טז")
    if n >= 10: s += tens[n // 10 - 1]; n %= 10
    if n: s += ones[n - 1]
    return s

if __name__ == "__main__":
    out = {q: [fetch(*r) for r in refs] for q, refs in REFS.items()}
    p = Path(__file__).with_name("contexts.json")
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for q, items in out.items():
        for it in items:
            print(q, it["he_ref"], it["license"], "|", it["text"][:110])
