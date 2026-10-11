"""Local Integration Benchmark: measures real latencies (not Mock). Usage: STORE_PATH=... .venv/bin/python scripts/perf.py"""
import json, sys, time, statistics
sys.path.insert(0, "src")
from kezohar.agent import Agent
from kezohar import llm as llm_client, config

ag = Agent(store_path="data/store/sources.jsonl")
out = {"kind": "Local Integration Benchmark", "model": config.llm_model()}

def med(xs):
    return round(statistics.median(xs), 3) if xs else None

# BM25 / hybrid timings
q = "מה מברכים על אורז?"
t = sorted([__import__("time").perf_counter() or 0 for _ in range(1)])
bm, hy = [], []
for _ in range(20):
    t0 = time.perf_counter(); ag.search.bm25.search(q, top_k=5); bm.append((time.perf_counter()-t0)*1000)
    t0 = time.perf_counter(); ag.search.search(q, top_k=5); hy.append((time.perf_counter()-t0)*1000)
out["bm25_ms_med"] = med(bm); out["hybrid_ms_med"] = med(hy)

# fast path
t0 = time.perf_counter(); r = ag.ask("מתי שקיעה היום בנתיבות?"); out["fast_ms"] = round((time.perf_counter()-t0)*1000, 1)

# full LLM answers (3 real calls, non-destructive)
full = []
for qq in ["מה מברכים על אורז?", "כמה זמן מחכים בין בשר לחלב?", "מה סדר הדלקת נרות חנוכה?"]:
    t0 = time.perf_counter(); r = ag.ask(qq, cache_ttl=0); dt = time.perf_counter()-t0
    full.append({"q": qq, "mode": r["mode"], "verdict": r.get("verdict"), "elapsed_s": r["elapsed_s"], "wall_s": round(dt,2),
                 "answer": r["answer"][:300]})
out["full_answers"] = full
print(json.dumps(out, ensure_ascii=False, indent=2))
