"""Phase 0 model benchmark for the Kezohar Torah agent.

For each candidate model (loaded one at a time via the `lms` CLI):
  1. Tool test   - model gets a dummy `search_halacha` tool; did it call it when it should?
  2. Answer test - model gets the question + fixed Sefaria passages (bench/contexts.json),
                   streamed; we measure time to first token, first sentence, total, tok/s.
Raw data -> bench/raw/<model>.json. Summary -> bench/results.md (via report.py).

Usage: python3 bench/run.py [model ...]     (stdlib only, reads LLM_BASE_URL from .env)
"""
import json, re, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
LMS = str(Path.home() / ".lmstudio/bin/lms")
CONTEXT_LEN = 8192

MODELS = [
    "dictalm-3.0-nemotron-12b-instruct",
    "qwen/qwen3.5-35b-a3b",
    "zai-org/glm-4.7-flash",
    "dictalm-3.0-24b-thinking",  # Hebrew-quality baseline only
]


def env(key):
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} missing in .env")


BASE = env("LLM_BASE_URL").rstrip("/")

SCOPE = ("אתה עוזר תורני של אפליקציית 'כזוהר הרקיע'. אתה עונה רק על הלכה, מנהגים, ברכות, זמנים, "
         "תפילות, צומות, שבת, חגים ולוח השנה העברי. על כל נושא אחר השב בנימוס, בעברית, שאינך עונה על כך.")

ANSWER_SYSTEM = SCOPE + """
כללים:
- ענה אך ורק על סמך המקורות שסופקו. אל תמציא מקורות, ציטוטים או פוסקים.
- אם אין במקורות תשובה, כתוב "אין לי מקור לכך".
- סדר הפסיקה: מרן השולחן ערוך ופוסקי הספרדים תחילה, ואחריהם הרמ"א והאשכנזים. כשיש מחלוקת הצג את שתי הדעות, הספרדית קודם.
- ציין את המקור בסוגריים, למשל (שולחן ערוך, אורח חיים רח:ז).
- עד 5 משפטים קצרים. בעברית בלבד."""

TOOL_SYSTEM = SCOPE + (" יש לך כלי search_halacha לחיפוש במקורות. בשאלה הלכתית חובה לקרוא לכלי לפני שעונים. "
                       "לשאלה מחוץ לתחום אל תקרא לכלי, וסרב בנימוס.")

TOOLS = [{
    "type": "function",
    "function": {
        "name": "search_halacha",
        "description": "חיפוש קטעים בספרי הלכה (שולחן ערוך, משנה ברורה, כף החיים ועוד). מחזיר קטעים עם מקור מדויק.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "שאילתת חיפוש בעברית"}},
            "required": ["query"],
        },
    },
}]


def load_questions():
    qs = []
    for line in (BENCH / "questions.md").read_text().splitlines():
        m = re.match(r"(\d+)\.\s+(.*?)\s*((?:\[\w+\])+)\s*$", line)
        if m:
            qs.append({"n": int(m[1]), "q": m[2], "tags": re.findall(r"\[(\w+)\]", m[3])})
    return qs


def post(path, body, stream=False, timeout=300):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=timeout)
    return r if stream else json.load(r)


def mem_used_gb():
    """Mac memory in use (wired + active + compressed), GB."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = int(re.search(r"page size of (\d+)", out)[1])
    get = lambda k: int(re.search(rf"{k}:\s+(\d+)", out)[1])
    pages = get("Pages wired down") + get("Pages active") + get("Pages occupied by compressor")
    return round(pages * page / 1e9, 1)


def lms(*args):
    return subprocess.run([LMS, *args], capture_output=True, text=True).stdout


def load_model(model):
    lms("unload", "--all")
    time.sleep(3)
    before = mem_used_gb()
    t = time.time()
    lms("load", model, "-c", str(CONTEXT_LEN), "-y")
    load_s = time.time() - t
    time.sleep(3)
    after = mem_used_gb()
    info = next((m for m in json.loads(lms("ps", "--json") or "[]") if m["identifier"] == model), {})
    return {"load_s": round(load_s, 1), "mem_before_gb": before, "mem_after_gb": after,
            "mem_delta_gb": round(after - before, 1),
            "file_gb": round(info.get("sizeBytes", 0) / 1e9, 1), "quant": (info.get("quantization") or {}).get("name")}


def tool_test(model, q):
    body = {"model": model, "temperature": 0.2, "max_tokens": 300, "reasoning_effort": "none",
            "tools": TOOLS, "tool_choice": "auto",
            "messages": [{"role": "system", "content": TOOL_SYSTEM}, {"role": "user", "content": q["q"]}]}
    t = time.time()
    r = post("/chat/completions", body)
    msg = r["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    call = calls[0]["function"] if calls else None
    args = None
    if call:
        try:
            args = json.loads(call["arguments"])
        except (TypeError, ValueError):
            args = call["arguments"]
    called = bool(call and call["name"] == "search_halacha")
    query_ok = called and isinstance(args, dict) and bool(re.search(r"[֐-׿]", str(args.get("query", ""))))
    tags = q["tags"]
    if "fast" in tags:
        verdict = "n/a"  # fast path answers these in code; LLM never sees them
    elif "refuse" in tags:
        verdict = "ok" if not called else "wrong"
    else:
        verdict = "ok" if query_ok else "wrong"
    return {"time_s": round(time.time() - t, 2), "called": called, "args": args,
            "content": (msg.get("content") or "").strip(), "verdict": verdict}


def build_user(q, ctx):
    if ctx:
        src = "\n".join(f"[{i}] {c['he_ref']}: {c['text']}" for i, c in enumerate(ctx, 1))
    else:
        src = "(לא נמצאו מקורות)"
    return f"מקורות:\n{src}\n\nשאלה: {q['q']}"


SENT_END = re.compile(r"[.!?](\s|$)")


def answer_test(model, q, ctx):
    body = {"model": model, "temperature": 0.2, "max_tokens": 700, "reasoning_effort": "none", "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": build_user(q, ctx)}]}
    t0 = time.time()
    ttft = tt_sentence = None
    text, reasoning, usage = "", "", {}
    for raw in post("/chat/completions", body, stream=True):
        line = raw.decode().strip()
        if not line.startswith("data:") or line == "data: [DONE]":
            continue
        d = json.loads(line[5:])
        if d.get("usage"):
            usage = d["usage"]
        for ch in d.get("choices", []):
            delta = ch.get("delta", {})
            reasoning += delta.get("reasoning_content") or delta.get("reasoning") or ""
            piece = delta.get("content") or ""
            if piece:
                if ttft is None:
                    ttft = time.time() - t0
                text += piece
                if tt_sentence is None and SENT_END.search(text):
                    tt_sentence = time.time() - t0
    total = time.time() - t0
    ntok = usage.get("completion_tokens", 0)
    gen_time = total - (ttft or 0)
    text = text.strip()
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    latin = len(re.findall(r"[A-Za-z]", text))
    return {
        "ttft_s": round(ttft, 2) if ttft else None,
        "first_sentence_s": round(tt_sentence or total, 2),
        "total_s": round(total, 2),
        "completion_tokens": ntok,
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
        "reasoning_chars": len(reasoning),
        "tok_per_s": round(ntok / gen_time, 1) if gen_time > 0 and ntok else None,
        "chars": len(text),
        "sentences": len(sentences),
        "latin_chars": latin,
        # mechanical behaviour checks only - NOT a halachic grade
        "cites_given_source": bool(ctx) and any(c["he_ref"].split(" ")[-1] in text for c in ctx),
        "says_no_source": "אין לי מקור" in text,
        "answer": text,
    }


def run_model(model, questions, contexts):
    print(f"\n=== {model} ===", flush=True)
    res = {"model": model, "load": load_model(model), "questions": []}
    print("  load:", res["load"], flush=True)
    post("/chat/completions", {"model": model, "max_tokens": 5, "reasoning_effort": "none",
                               "messages": [{"role": "user", "content": "שלום"}]})  # warm-up
    for q in questions:
        row = {**q, "tool": tool_test(model, q)}
        if "fast" not in q["tags"]:
            row["answer"] = answer_test(model, q, contexts.get(str(q["n"]), []))
        a = row.get("answer", {})
        print(f"  Q{q['n']:>2} tool={row['tool']['verdict']:<5} ttft={a.get('ttft_s')} total={a.get('total_s')} "
              f"tok/s={a.get('tok_per_s')}", flush=True)
        res["questions"].append(row)
    out = BENCH / "raw" / (model.replace("/", "__") + ".json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    questions = load_questions()
    assert len(questions) == 20, len(questions)
    contexts = json.loads((BENCH / "contexts.json").read_text())
    for m in sys.argv[1:] or MODELS:
        run_model(m, questions, contexts)
