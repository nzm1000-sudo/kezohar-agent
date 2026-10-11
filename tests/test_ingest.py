import json, sys, tempfile, os
from pathlib import Path
sys.path.insert(0, "src")
from kezohar import ingest

LIC = {
    "PD-Test": {"name": "t", "allows_full_text": True},
    "RESTRICTED": {"name": "r", "allows_full_text": False},
}

def _raw(text="טקסט בדיקה שבת", lic="PD-Test", ref="אורח חיים רח:ז", work="שולחן ערוך"):
    return {"work_title": work, "author": "א", "reference": ref, "text": text,
            "language": "he", "tradition": "sephardi", "license": lic,
            "source_url": "", "version": "v1"}

def test_license_block():
    srcs, err = ingest.prepare_source(_raw(lic="RESTRICTED"), LIC)
    assert srcs == [] and "license" in err

def test_unknown_license_block():
    srcs, err = ingest.prepare_source(_raw(lic="NOPE"), LIC)
    assert srcs == [] and err

def test_normalized_saved_and_original_kept():
    srcs, err = ingest.prepare_source(_raw(text="שַׁבָּת"), LIC)
    assert err == "" and len(srcs) == 1
    assert srcs[0].text == "שַׁבָּת"
    assert srcs[0].normalized_text == "שבת"

def test_dedup_and_resume(tmp_path=None):
    import tempfile
    d = tempfile.mkdtemp()
    store = os.path.join(d, "s.jsonl")
    prog = os.path.join(d, "prog.json")
    raws = [_raw(text="אורז בורא פרי האדמה"), _raw(text="אורז בורא פרי האדמה")]
    r1 = ingest.ingest_sources(raws, store, licenses=LIC, progress_path=prog)
    assert r1["added"] == 1 and r1["skipped_dup"] == 1
    # second run resumes / dedups — adds 0
    r2 = ingest.ingest_sources(raws, store, licenses=LIC, progress_path=prog)
    assert r2["added"] == 0

def test_yalkut_yosef_blocked():
    raw = _raw(text="טקסט כלשהו", lic="RESTRICTED", work="ילקוט יוסף")
    srcs, err = ingest.prepare_source(raw, LIC)
    assert srcs == []
