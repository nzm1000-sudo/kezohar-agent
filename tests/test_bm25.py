import sys
sys.path.insert(0, "src")
from kezohar import ingest, bm25

def _idx():
    import json
    raws = json.loads(open("data/sample_sources/sources.json", encoding="utf-8").read())
    import tempfile, os
    from kezohar import ingest as ing
    lic = ing.load_licenses()
    all_srcs = []
    for r in raws:
        srcs, err = ing.prepare_source(r, lic)
        assert err == "", err
        all_srcs.extend(srcs)
    idx = bm25.BM25Index().build(all_srcs)
    return idx

def test_rice():
    idx = _idx()
    res = idx.search("מה מברכים על אורז?", top_k=3)
    assert res, "no results for rice"
    assert "אורז" in res[0]["text"]

def test_meat_milk_wait():
    idx = _idx()
    res = idx.search("כמה זמן מחכים בין בשר לחלב", top_k=3)
    assert res and ("שש שעות" in res[0]["text"] or "בשר" in res[0]["text"])

def test_chanuka():
    idx = _idx()
    res = idx.search("סדר הדלקת נרות חנוכה", top_k=3)
    assert res and "חנוכה" in res[0]["text"]

def test_returns_ids_and_refs():
    idx = _idx()
    res = idx.search("אורז", top_k=2)
    for r in res:
        assert r["source_id"] and r["reference"] and r["text"] and r["score"] > 0

def test_no_dup_ids():
    idx = _idx()
    res = idx.search("ברכה", top_k=10)
    ids = [r["source_id"] for r in res]
    assert len(ids) == len(set(ids))

def test_niqqud_query():
    idx = _idx()
    a = idx.search("שַׁבָּת", top_k=5)
    b = idx.search("שבת", top_k=5)
    assert [r["source_id"] for r in a] == [r["source_id"] for r in b]
