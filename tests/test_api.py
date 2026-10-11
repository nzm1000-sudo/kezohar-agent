import sys
sys.path.insert(0, "src")
import os
os.environ.setdefault("STORE_PATH", "data/store/sources.jsonl")
from fastapi.testclient import TestClient
from kezohar import api

c = TestClient(api.app)

def test_health():
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_search():
    r = c.post("/search", json={"query": "אורז"})
    assert r.status_code == 200
    assert r.json()["results"]

def test_search_missing():
    r = c.post("/search", json={})
    assert r.status_code == 400

def test_ask_fast():
    r = c.post("/ask", json={"question": "מתי שקיעה היום בנתיבות?"})
    assert r.status_code == 200
    j = r.json()
    assert j["mode"] == "fast" and j["elapsed_s"] < 1.0

def test_ask_bad_json():
    r = c.post("/ask", content=b"{bad", headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)

def test_ask_missing():
    r = c.post("/ask", json={})
    assert r.status_code == 400

def test_ask_stream():
    r = c.post("/ask", json={"question": "מתי שקיעה היום בנתיבות?", "stream": True})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: sources" in r.text and "event: done" in r.text

def test_ask_parallel_and_repeat():
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(lambda: c.post("/ask", json={"question": "מתי שקיעה היום בנתיבות?"})) for _ in range(4)]
        for f in futs:
            assert f.result().status_code == 200
    r1 = c.post("/ask", json={"question": "מתי שקיעה היום בנתיבות?"})
    r2 = c.post("/ask", json={"question": "מתי שקיעה היום בנתיבות?"})
    assert r1.json()["answer"] == r2.json()["answer"]
