"""End-to-end: 18 scenarios from master prompt section 16 (local integration, Mock where external)."""
import sys, os
sys.path.insert(0, "src")
os.environ.setdefault("STORE_PATH", "data/store/sources.jsonl")
from fastapi.testclient import TestClient
from kezohar import api, citations
from kezohar.agent import Agent

c = TestClient(api.app)

def _agent_offline():
    return Agent(store_path="data/store/sources.jsonl", base_url="http://127.0.0.1:9/v1")

def test_01_exact_source():
    r = c.post("/search", json={"query": "אורז בורא פרי האדמה"})
    assert r.json()["results"] and "אורז" in r.json()["results"][0]["text"]

def test_02_no_source():
    ag = Agent(sources=[], base_url="")
    r = ag.ask("שאלה הלכתית בלי מקור כלל?")
    assert r["verdict"] == "no_source"

def test_03_irrelevant():
    v = citations.verify_answer("מה מברכים על אורז?",
        "מחכים שש שעות (שולחן ערוך, יורה דעה פט:א).",
        [{"reference": "שולחן ערוך, יורה דעה פט:א", "text": "אכל בשר לא יאכל גבינה עד שישהה שש שעות"}])
    assert v["verdict"] == "irrelevant"

def test_04_invented_ref():
    v = citations.verify_answer("מה מברכים על אורז?", "כך (שולחן ערוך, אורח חיים תקפז:ג).",
        [{"reference": "שולחן ערוך, אורח חיים רח:ז", "text": "האורז מברך בורא פרי האדמה"}])
    assert v["verdict"] == "invalid_citation"

def test_05_sephardi_ashkenazi_both():
    ag = _agent_offline()
    r = ag.ask("כמה זמן מחכים בין בשר לחלב?")
    assert r["sources"]  # sources retrieved; LLM offline -> sources-only
    assert r["mode"] == "sources-only"

def test_06_zmanim():
    r = c.post("/ask", json={"question": "מתי שקיעה היום בנתיבות?"})
    assert r.json()["mode"] == "fast"

def test_07_out_of_scope():
    r = c.post("/ask", json={"question": "מה מזג האוויר מחר?"})
    assert r.json()["verdict"] == "out_of_scope"

def test_08_llm_off():
    ag = _agent_offline()
    r = ag.ask("מה מברכים על אורז?")
    assert r["mode"] == "sources-only" and "מצב חיפוש" in r["answer"]

def test_09_qdrant_off():
    # MockVectorStore always works locally; real Qdrant absent -> hybrid still returns bm25
    from kezohar.hybrid import HybridSearch
    from kezohar import ingest
    import json
    raws = json.loads(open("data/sample_sources/sources.json", encoding="utf-8").read())
    lic = ingest.load_licenses()
    srcs = []
    for x in raws:
        s, _ = ingest.prepare_source(x, lic)
        srcs.extend(s)
    h = HybridSearch(srcs)
    h.vector.docs = []  # simulate vector down
    h.vector.vecs = []
    res = h.search("אורז", top_k=3)
    assert res and res[0]["backend"].startswith("bm25")

def test_10_no_network():
    from kezohar import llm
    ok, _ = llm.check_health("http://127.0.0.1:9/v1", timeout=2)
    assert ok is False

def test_11_bad_json():
    r = c.post("/ask", content=b"{oops", headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)

def test_12_sse_cut():
    r = c.post("/ask", json={"question": "מתי שקיעה היום בנתיבות?", "stream": True})
    assert "event: done" in r.text

def test_13_parallel():
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        rs = list(ex.map(lambda _: c.post("/search", json={"query": "שבת"}), range(4)))
    assert all(x.status_code == 200 for x in rs)

def test_14_repeat_cache():
    ag = _agent_offline()
    ag.ask("מה מברכים על אורז?")
    r2 = ag.ask("מה מברכים על אורז?")
    assert r2.get("cached") is True

def test_15_no_dups():
    r = c.post("/search", json={"query": "ברכה", "top_k": 10})
    ids = [x["source_id"] for x in r.json()["results"]]
    assert len(ids) == len(set(ids))

def test_16_restore():
    from kezohar.ingest import load_store
    docs = load_store("data/store/sources.jsonl")
    assert len(docs) == 15

def test_17_hebrew_norm():
    from kezohar import hebrew
    assert hebrew.normalize("שַׁבָּת") == hebrew.normalize("שבת")

def test_18_licenses():
    from kezohar.ingest import load_licenses, license_allows
    lic = load_licenses()
    assert license_allows(lic, "PD-ShulchanAruch-1893") is True
    assert license_allows(lic, "RESTRICTED") is False
