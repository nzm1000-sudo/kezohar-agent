import sys
sys.path.insert(0, "src")
import os
os.environ.setdefault("STORE_PATH", "data/store/sources.jsonl")
from fastapi.testclient import TestClient
from kezohar import api

import pytest
from kezohar.agent import Agent
from kezohar.models import Source

@pytest.fixture(autouse=True)
def isolated_agent(monkeypatch):
    monkeypatch.setattr(api, '_agent', Agent(sources=[Source(source_id='test-rice', work_title='ספר בדיקה', reference='בדיקה א:א', text='אורז מברכים מזונות')], base_url=''))
    monkeypatch.setattr(api.llm_client, 'check_health', lambda *a, **k: (False, []))

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

def test_research_endpoint_uses_engine(monkeypatch):
    monkeypatch.setattr(Agent, 'research', lambda self,q,top_k=5:{'answer':'מקור מאומת','sources':[], 'mode':'web-evidence'})
    r=c.post('/research',json={'question':'מה מברכים על אורז?'})
    assert r.status_code==200 and r.json()['mode']=='web-evidence'
    assert c.post('/research',json={}).status_code==400
    assert c.post('/research',json={'question':'אורז','top_k':'bad'}).status_code==400
    assert c.post('/ask',json={'question':'ברכת אורז','research':True}).json()['mode']=='web-evidence'

def test_stream_sources_precede_inference_and_reuse_retrieval(monkeypatch):
    events=[]
    class Fake:
        def search_only(self,q,top_k=5):events.append('retrieval');return [{'source_id':'x','text':'אורז'}]
        def ask(self,q,**kwargs):
            events.append('llm');assert kwargs['retrieved_sources'][0]['source_id']=='x'
            return {'answer':'תשובה','sources':kwargs['retrieved_sources'],'mode':'llm','verdict':'ok'}
    monkeypatch.setattr(api,'get_agent',lambda:Fake())
    stream=api._stream_local('מה מברכים על אורז?')
    first=next(stream)
    assert first.startswith('event: sources') and events==['retrieval']
    assert 'event: answer' in next(stream) and events==['retrieval','llm']
