"""Sefaria connector: fetch Hebrew texts by ref, respecting licenses.

Only imports full text when the mapped license allows it.
Yalkut Yosef / Chazon Ovadia and any copyrighted work -> blocked (RESTRICTED).
Usage: .venv/bin/python -m kezohar.sefaria "Shulchan_Arukh,_Orach_Chayim.208" --out data/sample_sources/sefaria_oc208.json
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request

API = "https://www.sefaria.org/api/texts/"

BLOCKED_WORKS = ["ילקוט יוסף", "Yalkut Yosef", "חזון עובדיה", "Chazon Ovadia",
                 "Yalkut_Yosef", "Chazon_Ovadia"]

LICENSE_MAP = {
    "public domain": "PD-ShulchanAruch-1893",
    "publicdomain": "PD-ShulchanAruch-1893",
    "cc-by": "CC-BY",
    "cc-by-sa": "CC-BY-SA",
}

TAG_RE = re.compile(r"<[^>]+>")

def clean_html(s):
    s = TAG_RE.sub("", s or "")
    return html.unescape(s).strip()

def is_blocked(ref):
    return any(b.lower() in (ref or "").lower() for b in BLOCKED_WORKS)

def fetch_ref(ref, lang="he", timeout=20):
    """Fetch one ref from Sefaria API. Returns dict or raises."""
    if is_blocked(ref):
        raise ValueError(f"blocked copyrighted work: {ref}")
    url = API + urllib.parse.quote(ref, safe="") + f"?lang={lang}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def to_raw_records(data, tradition="sephardi"):
    """Convert Sefaria response to raw ingest records."""
    lic_raw = str(data.get("license", "") or "").lower()
    lic = next((v for k, v in LICENSE_MAP.items() if k in lic_raw), "")
    if not lic:
        # unknown license -> do not import full text
        return [], f"unknown license {data.get('license')!r} for {data.get('ref')}"
    he_ref = data.get("heRef", "") or data.get("ref", "")
    version = ""
    try:
        vs = data.get("versions") or []
        if vs:
            version = vs[0].get("versionTitle", "")
    except Exception:
        pass
    text = data.get("he") or data.get("text") or []
    if isinstance(text, str):
        text = [text]
    # flatten nested arrays
    flat = []
    def _flat(x):
        if isinstance(x, list):
            for i in x:
                _flat(i)
        elif isinstance(x, str) and clean_html(x):
            flat.append(clean_html(x))
    _flat(text)
    recs = []
    for i, t in enumerate(flat, start=1):
        recs.append({"work_title": "שולחן ערוך", "author": "רבי יוסף קארו",
                     "reference": f"{he_ref} סעיף {i}" if len(flat) > 1 else he_ref,
                     "text": t, "language": "he", "tradition": tradition,
                     "license": lic, "source_url": "https://www.sefaria.org/" + (data.get("ref", "")),
                     "version": version or str(data.get("versionTitle", ""))})
    return recs, ""

def main():
    refs = sys.argv[1:]
    out = "data/sample_sources/sefaria.json"
    if "--out" in refs:
        i = refs.index("--out")
        out = refs[i+1]
        refs = refs[:i]
    all_recs, errs = [], []
    for ref in refs:
        try:
            data = fetch_ref(ref)
            recs, err = to_raw_records(data)
            if err:
                errs.append(err)
            all_recs.extend(recs)
            print(f"{ref}: {len(recs)} passages, license={data.get('license')}")
        except Exception as e:
            errs.append(f"{ref}: {e}")
            print(f"{ref}: ERROR {e}")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_recs, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(all_recs)} records -> {out}; errors={len(errs)}")

if __name__ == "__main__":
    main()
