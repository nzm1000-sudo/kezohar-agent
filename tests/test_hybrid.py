import sys
sys.path.insert(0, "src")
from kezohar import hybrid, ingest

def _sources():
    import json
    raws = json.loads(open("data/sample_sources/sources.json", encoding="utf-8").read())
    lic = ingest.load_licenses()
    out = []
    for r in raws:
        srcs, err = ingest.prepare_source(r, lic)
        assert err == ""
        out.extend(srcs)
    return out

def test_hybrid_returns_fused():
    h = hybrid.HybridSearch(_sources())
    res = h.search("מה מברכים על אורז?", top_k=3)
    assert res and all(r["source_id"] and r["reference"] and r["text"] for r in res)
    assert any("hybrid:" in r["backend"] for r in res)

def test_hybrid_rrf_prefers_both():
    h = hybrid.HybridSearch(_sources())
    res = h.search("שש שעות בשר גבינה", top_k=3)
    assert res and "בשר" in res[0]["text"]

def test_hybrid_empty():
    h = hybrid.HybridSearch([])
    assert h.search("שבת") == []

def test_rrf_k_documented():
    assert hybrid.RRF_K == 60
