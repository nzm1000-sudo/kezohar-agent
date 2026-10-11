"""Phase 0 model benchmark for the Kezohar Torah agent.

For each candidate model (loaded one at a time via the `lms` CLI):
  1. Tool test   - model gets a dummy `search_halacha` tool; did it call it when it should?
  2. Answer test - model gets the question + fixed Sefaria passages (bench/contexts.json),
                   streamed; we measure time to first token, first sentence, total, tok/s.
Raw data -> bench/<out>/<model>.json (default bench/raw). Summary -> bench/results.md (via report.py).
Each run also records machine load (load average, busiest processes) so results taken
under load can be told apart.

Usage: python3 bench/run.py [--out DIR] [model ...]   (stdlib only, reads LLM_BASE_URL from .env)
"""
import argparse, codecs, http.client, json, os, re, socket, subprocess, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
LMS = str(Path.home() / ".lmstudio/bin/lms")
CONTEXT_LEN = 8192

MODELS = [
    "dictalm-3.0-nemotron-12b-instruct",
    "qwen/qwen3.5-35b-a3b",
    "zai-org/glm-4.7-flash",
    "google/gemma-4-26b-a4b",
    "dictalm-3.0-24b-thinking",  # Hebrew-quality baseline only
]


class BenchmarkError(Exception):
    """Base error for benchmark infrastructure failures."""


class BenchmarkConnectionError(BenchmarkError):
    """The LLM server could not be reached or returned a bad response."""


def env(key, path=None):
    """Read KEY from a .env-style file. Skips blanks/comments, strips quotes.

    Raises SystemExit with a clear message when the file or key is missing.
    """
    p = Path(path) if path is not None else ROOT / ".env"
    if not p.exists():
        raise SystemExit(
            f"קובץ ההגדרות חסר: {p} — צור אותו מתוך .env.example "
            f"(נדרשת שורה מסוג {key}=...). (config file missing: {p})"
        )
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip("'\"")
    raise SystemExit(f"{key} חסר בקובץ {p} — הוסף שורה מסוג {key}=... .")


def get_base():
    """LLM base URL, loaded lazily so import/tests don't crash without .env."""
    global BASE
    if BASE is None:
        BASE = env("LLM_BASE_URL").rstrip("/")
    return BASE


try:
    BASE = env("LLM_BASE_URL").rstrip("/")
except SystemExit:
    BASE = None  # a clear error is raised later at request time (see post())

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
    """POST JSON to the LM Studio server.

    Raises BenchmarkConnectionError with a clear (Hebrew + English) message on:
    HTTP errors, unreachable server, timeouts, and corrupt JSON responses.
    The measurement methodology itself is unchanged — only failures are
    reported clearly instead of crashing with a raw traceback.
    """
    base = get_base()  # clear SystemExit here if the config file is missing
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            e.close()  # the error object holds the socket; release it
        except Exception:
            pass
        raise BenchmarkConnectionError(
            f"שגיאת HTTP {code} מהשרת {base}{path} — בדוק שהמודל טעון ב-LM Studio ושכתובת השרת נכונה. "
            f"(HTTP error {code} from {base}{path})"
        ) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise BenchmarkConnectionError(
                f"הבקשה ל-{base}{path} נכשלה ב-timeout אחרי {timeout} שניות — השרת עמוס או לא מגיב. "
                f"(request to {base}{path} timed out after {timeout}s)"
            ) from e
        raise BenchmarkConnectionError(
            f"שרת LM Studio אינו עונה ב-{base} — פתח את LM Studio והפעל את השרת, "
            f"ובדוק את LLM_BASE_URL בקובץ .env. (server unreachable at {base}: {e.reason})"
        ) from e
    except (TimeoutError, socket.timeout, ConnectionError, OSError) as e:
        raise BenchmarkConnectionError(
            f"חיבור הרשת ל-{base}{path} נכשל או נותק ({e}) — בדוק שהשרת פעיל והרשת תקינה. "
            f"(network failure for {base}{path}: {e})"
        ) from e
    if stream:
        return r  # ownership passes to the caller: iter_sse_lines() always closes it
    try:
        return json.load(r)
    except (ValueError, UnicodeDecodeError) as e:
        raise BenchmarkConnectionError(
            f"השרת החזיר תגובה פגומה (לא JSON תקין) ב-{path}. "
            f"(invalid JSON response on {path}: {e})"
        ) from e
    finally:
        try:
            r.close()
        except Exception:
            pass


def mem_used_gb():
    """Mac memory in use (wired + active + compressed), GB."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = int(re.search(r"page size of (\d+)", out)[1])
    get = lambda k: int(re.search(rf"{k}:\s+(\d+)", out)[1])
    pages = get("Pages wired down") + get("Pages active") + get("Pages occupied by compressor")
    return round(pages * page / 1e9, 1)


def lms(*args):
    return subprocess.run([LMS, *args], capture_output=True, text=True).stdout


def machine_load():
    """Load average + the busiest non-LM-Studio processes right now."""
    out = subprocess.run(["ps", "-Ao", "pcpu=,command="], capture_output=True, text=True).stdout
    procs = []
    for line in out.splitlines():
        cpu, _, cmd = line.strip().partition(" ")
        argv = cmd.split()
        name = Path(argv[0]).name
        if name in ("node", "python3", "python") and len(argv) > 1:
            name += " " + Path(argv[1]).name  # show which script is busy
        if float(cpu) >= 20 and "LM Studio" not in cmd and ".lmstudio" not in cmd and "llmworker" not in name.lower():
            procs.append((float(cpu), name))
    procs.sort(reverse=True)
    return {"loadavg_1m": round(os.getloadavg()[0], 1), "cores": os.cpu_count(),
            "busy_procs": [f"{n} {c:.0f}%" for c, n in procs[:5]]}


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
    try:
        msg = r["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise BenchmarkConnectionError(
            "השרת החזיר תשובה במבנה לא צפוי (חסר choices/message) — "
            "בדוק שהמודל הנכון טעון ב-LM Studio. "
            f"(malformed chat response, missing choices/message: {e})"
        ) from e
    if not isinstance(msg, dict):
        raise BenchmarkConnectionError(
            "השרת החזיר הודעה במבנה לא צפוי (message אינו אובייקט). "
            "(malformed chat response: message is not an object)"
        )
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


SENT_END_CHARS = ".!?…׃"
SENT_END = re.compile(r"[.!?…׃](\s|$)")


def split_sentences(text):
    """Split Hebrew/English text into sentences.

    Same terminators as SENT_END (Latin .!? plus Hebrew … and ׃ sof-pasuq).
    The colon ':' is deliberately NOT a terminator so citations like רח:ז
    don't split sentences. Methodology unchanged — only the charset grew.
    """
    return [s for s in re.split(r"(?<=[.!?…׃])\s+", text) if s.strip()]


_HEB = "֐-׿"  # whole Hebrew Unicode block (incl. final forms)


def _unify_finals(s):
    return (s.replace("ך", "כ").replace("ם", "מ").replace("ן", "נ")
             .replace("ף", "פ").replace("ץ", "צ"))


def _norm_cite(s):
    """Normalize a citation for comparison.

    Unifies ׃→:, final-letter forms → regular, strips geresh/gershayim and
    punctuation, and unifies every separator run (spaces, colons) into one
    ':'. So 'רח:ז', 'רח׃ז' and 'רח ז' all become 'רח:ז'. A bare 'רחז'
    (no separator at all) deliberately does NOT match — requiring a
    separator is what keeps 'ח:ז' (siman 8) from matching inside
    'רח:ז' (siman 208).
    """
    s = _unify_finals(s.replace("׃", ":"))
    s = re.sub(r"[׳״’ʼ′'\"`.,;()\[\]{}]", "", s)
    return re.sub(r"[:\s]+", ":", s).strip(":")


def _plain_words(s):
    """Copy of s with finals unified and punctuation stripped, spaces kept."""
    s = _unify_finals(s.replace("׃", " "))
    return re.sub(r"[׳״’ʼ′'\"`.,;:()\[\]{}]", "", s)


def _bounded(haystack, needle):
    """Substring match with Hebrew-letter/digit boundaries on both sides."""
    return re.search(r"(?<![%s0-9])%s(?![%s0-9])" % (_HEB, re.escape(needle), _HEB),
                     haystack) is not None


def cites_source(text, ctx):
    """True if the answer cites one of the given sources.

    Three layers, first match wins:
    1. exact raw check with Hebrew-letter boundaries (original behaviour,
       hardened so 'ח:ז' can't match inside 'רח:ז');
    2. normalized comparison (geresh/space/׃ variants, same boundaries);
    3. spelled-out 'סימן X סעיף Y' with boundaries around each number, so
       siman ח (8) can't match 'סימן רח' (208) and seif ז (7) can't match
       'סעיף טז' (16). No methodology change — every answer that cited
       before still cites now; only unrelated-source collisions are cut.
    """
    if not ctx or not text:
        return False
    norm_text = _norm_cite(text)
    plain_text = _plain_words(text)
    for c in ctx:
        last = c.get("he_ref", "").split(" ")[-1]
        if not last:
            continue
        if _bounded(text, last):
            return True
        nlast = _norm_cite(last)
        if nlast and _bounded(norm_text, nlast):
            return True
        if ":" in nlast:
            siman, _, seif = nlast.partition(":")
            siman = re.sub(r"\s+", "", _plain_words(siman))
            seif = re.sub(r"\s+", "", _plain_words(seif))
            if not (siman and seif):
                continue
            # keywords go through the same final-letter unification as
            # plain_text (סימן→סימנ), otherwise they can never match.
            siman_kw, seif_kw = _unify_finals("סימן"), _unify_finals("סעיף")
            siman_ok = re.search(r"(?<![%s])%s\s*%s(?![%s0-9])" % (_HEB, siman_kw, re.escape(siman), _HEB),
                                 plain_text)
            seif_ok = re.search(r"(?<![%s])%s\s*%s(?![%s0-9])" % (_HEB, seif_kw, re.escape(seif), _HEB),
                                plain_text)
            if siman_ok and seif_ok:
                return True
    return False


def iter_sse_lines(resp):
    """Yield decoded SSE lines from a streaming response; always close it.

    - reassembles a line split across reads (buffering),
    - decodes incrementally so UTF-8 split between reads stays intact,
    - skips undecodable bytes, and closes resp in every exit path
      (normal end, exception, or a mid-answer network break).
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    try:
        while True:
            raw = resp.read(65536)
            if not raw:
                break
            if isinstance(raw, str):
                buf += raw
            else:
                buf += decoder.decode(raw)
            *ready, buf = buf.split("\n")
            for ln in ready:
                yield ln.strip()
        tail = (buf + decoder.decode(b"", final=True)).strip()
        if tail:
            yield tail
    finally:
        try:
            resp.close()
        except Exception:
            pass


def answer_test(model, q, ctx):
    body = {"model": model, "temperature": 0.2, "max_tokens": 700, "reasoning_effort": "none", "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": build_user(q, ctx)}]}
    t0 = time.time()
    ttft = tt_sentence = None
    text, reasoning, usage = "", "", {}
    truncated = False
    try:
        for line in iter_sse_lines(post("/chat/completions", body, stream=True)):
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            try:
                d = json.loads(line[5:])
            except ValueError:
                continue  # skip one corrupt SSE chunk; timing methodology unchanged
            if not isinstance(d, dict):
                continue
            if isinstance(d.get("usage"), dict):
                usage = d["usage"]
            choices = d.get("choices", [])
            if not isinstance(choices, list):
                continue
            for ch in choices:
                if not isinstance(ch, dict):
                    continue
                delta = ch.get("delta", {})
                if not isinstance(delta, dict):
                    continue
                reasoning += delta.get("reasoning_content") or delta.get("reasoning") or ""
                piece = delta.get("content") or ""
                if piece:
                    if ttft is None:
                        ttft = time.time() - t0
                    text += piece
                    if tt_sentence is None and SENT_END.search(text):
                        tt_sentence = time.time() - t0
    except (TimeoutError, socket.timeout, ConnectionError, OSError,
            http.client.HTTPException) as e:
        # Network broke mid-answer: keep what arrived and flag it, instead of
        # crashing the whole model run. Timing covers the received part only.
        truncated = True
        text += f"\n[תשובה נקטעה — החיבור נותק באמצע: {e}]"
    total = time.time() - t0
    ntok = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
    gen_time = total - (ttft or 0)
    text = text.strip()
    sentences = split_sentences(text)
    latin = len(re.findall(r"[A-Za-z]", text))
    return {
        "ttft_s": round(ttft, 2) if ttft else None,
        "first_sentence_s": round(tt_sentence or total, 2),
        "total_s": round(total, 2),
        "completion_tokens": ntok,
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
        "reasoning_chars": len(reasoning),
        "tok_per_s": round(ntok / gen_time, 1) if gen_time > 0.25 and ntok > 1 else None,  # too short to measure
        "chars": len(text),
        "sentences": len(sentences),
        "latin_chars": latin,
        # mechanical behaviour checks only - NOT a halachic grade
        "cites_given_source": cites_source(text, ctx),
        "says_no_source": "אין לי מקור" in text,
        "truncated": truncated,  # True when the network broke mid-answer
        "answer": text,
    }


def run_model(model, questions, contexts, out_dir):
    print(f"\n=== {model} ===", flush=True)
    res = {"model": model, "load": load_model(model), "conditions": {"start": machine_load()}, "questions": []}
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
    res["conditions"]["end"] = machine_load()
    res["conditions"]["finished_at"] = time.strftime("%Y-%m-%d %H:%M")
    print("  conditions:", res["conditions"], flush=True)
    out = out_dir / (model.replace("/", "__") + ".json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    questions = load_questions()
    assert len(questions) == 20, len(questions)
    contexts = json.loads((BENCH / "contexts.json").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="raw", help="output folder under bench/")
    ap.add_argument("models", nargs="*", default=MODELS)
    a = ap.parse_args()
    for m in a.models:
        run_model(m, questions, contexts, BENCH / a.out)
