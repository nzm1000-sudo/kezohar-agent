"""Blind Hebrew-quality review sheets.

  python3 bench/hebrew_review.py           -> bench/hebrew-review.md       (all models, all answered questions)
  python3 bench/hebrew_review.py --short   -> bench/hebrew-review-short.md (3 models, 5 longest-answer questions)
      each with its key (letter -> model, per question) in a separate *-key.json file
  python3 bench/hebrew_review.py --score   -> reads the filled-in scores of every sheet, prints average per model

Answers are cut at a leaked chat token ("<|..."), which would otherwise identify the model.
Letters are reshuffled for every question (fixed seed) so a model can't be recognised
by position. Only questions that got an LLM answer are included ([fast] ones are not).
"""
import json, random, re, statistics, sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
SCORE_LINE = "ציון עברית (1-5):"

SHEETS = {
    "full": {"name": "hebrew-review", "models": None, "questions": None},
    "short": {"name": "hebrew-review-short", "questions": 5,
              "models": ["qwen/qwen3.5-35b-a3b", "google/gemma-4-26b-a4b", "dictalm-3.0-nemotron-12b-instruct"]},
}


def paths(cfg):
    return BENCH / f"{cfg['name']}.md", BENCH / f"{cfg['name']}-key.json"


def answer_text(run, i):
    return run["questions"][i]["answer"]["answer"].split("<|")[0].strip()


def build(cfg):
    sheet, keyfile = paths(cfg)
    if sheet.exists() and re.search(rf"{re.escape(SCORE_LINE)}\*\*\s*[1-5]", sheet.read_text()):
        raise SystemExit(f"{sheet.name} already has scores — not overwriting. Move it aside first.")
    runs = [json.loads(p.read_text()) for p in sorted((BENCH / "raw").glob("*.json"))]
    if cfg["models"]:
        runs = [r for r in runs if r["model"] in cfg["models"]]
        assert len(runs) == len(cfg["models"]), "missing raw results for a model"
    idx = [i for i, q in enumerate(runs[0]["questions"]) if "answer" in q]
    if cfg["questions"]:  # keep the N questions with the most answer text across these models
        idx = sorted(idx, key=lambda i: -sum(len(answer_text(r, i)) for r in runs))[:cfg["questions"]]
        idx.sort()
    rng = random.Random(613)
    letters = "ABCDEFGHIJ"[:len(runs)]
    key, out = {}, [
        "# בדיקת עברית — עיוורת", "",
        "לכל שאלה מופיעות תשובות של כמה מודלים, מסומנות באותיות. האותיות מתערבבות בכל שאלה מחדש.",
        f"כתוב ציון מ-1 (גרוע) עד 5 (מצוין) אחרי \"{SCORE_LINE}\". דרג רק את העברית: ניסוח, בהירות, טבעיות.",
        "את הנכונות ההלכתית בודקים בנפרד. בסיום הרץ: `python3 bench/hebrew_review.py --score`",
        "הערה: תשובה שהמודל המשיך אחריה לכתוב טקסט מומצא נחתכה כאן בנקודה שבה הייתה אמורה להיגמר"
        " (הטקסט המלא נמצא ב-results.md).", "",
    ]
    for i in idx:
        q = runs[0]["questions"][i]
        order = list(range(len(runs)))
        rng.shuffle(order)
        key[str(q["n"])] = {letters[j]: runs[m]["model"] for j, m in enumerate(order)}
        out += ["---", "", f"## שאלה {q['n']}: {q['q']}", ""]
        for j, m in enumerate(order):
            ans = answer_text(runs[m], i) or "(ריק)"
            out += [f"### {letters[j]}", "", "> " + ans.replace("\n", "\n> "), "", f"**{SCORE_LINE}** ", ""]
    sheet.write_text("\n".join(out) + "\n")
    keyfile.write_text(json.dumps(key, ensure_ascii=False, indent=1))
    print(f"wrote {sheet.name} ({len(key)} questions, {len(runs)} models) and {keyfile.name}")


SCORE_RE = re.compile(r"(?<![\d.,])([1-5](?:[.,]5)?)(?![\d.,])")  # 4, 3.5, 3,5


def read_entries(cfg):
    """[(question, model, score or None, note)] for every answer the reviewer filled in.

    The score and any free-text note (e.g. "הבין לא נכון") may be written anywhere inside an
    answer's section (after the score label, on the lines below it, or even above it), as long
    as it is not inside the quoted answer itself (lines starting with ">").
    """
    sheet, keyfile = paths(cfg)
    if not (sheet.exists() and keyfile.exists()):
        return []
    key = json.loads(keyfile.read_text())
    entries, q, letter, filled = [], None, None, None

    def flush():
        text = " ".join(filled).strip() if filled is not None else ""
        if text:
            m = SCORE_RE.search(text)
            s = float(m[1].replace(",", ".")) if m else None
            note = (text[:m.start()] + text[m.end():]).strip(" -–:,") if m else text
            entries.append((q, key[q][letter], s, note))

    for line in sheet.read_text().splitlines():
        if (m := re.match(r"## שאלה (\d+):", line)) or (n := re.match(r"### ([A-J])\s*$", line)) or line == "---":
            flush()
            filled = None
            if m:
                q = m[1]
            elif line != "---":
                letter = n[1]
                filled = []
        elif filled is not None and not line.lstrip().startswith(">"):
            filled.append(line.replace(SCORE_LINE, "").replace("**", ""))
    flush()
    return entries


MISUNDERSTOOD = re.compile(r"לא הבין|הבין לא נכון|לא נכון")


def score():
    per_sheet = {n: read_entries(cfg) for n, cfg in SHEETS.items()}
    per_sheet = {n: e for n, e in per_sheet.items() if e}
    if not per_sheet:
        print("לא נמצאו ציונים באף קובץ דירוג.")
        return
    models = sorted({e[1] for es in per_sheet.values() for e in es})
    avg = lambda xs: f"{statistics.mean(xs):.2f} ({len(xs)})" if xs else "—"
    rows = []
    for mdl in models:
        cols = [avg([s for _, m, s, _ in es if m == mdl and s is not None]) for es in per_sheet.values()]
        allv = [s for es in per_sheet.values() for _, m, s, _ in es if m == mdl and s is not None]
        wrong = sorted({int(q) for es in per_sheet.values() for q, m, _, note in es
                        if m == mdl and MISUNDERSTOOD.search(note)})
        rows.append((statistics.mean(allv) if allv else 0, mdl, cols, avg(allv), wrong))
    names = {"full": "ארוך", "short": "קצר"}
    print("| מודל | " + " | ".join(f"ממוצע {names[n]}" for n in per_sheet) + " | ממוצע כולל | 'הבין לא נכון' בשאלות |")
    print("|---|" + "---|" * len(per_sheet) + "---|---|")
    for _, mdl, cols, total, wrong in sorted(rows, reverse=True):
        print(f"| {mdl} | " + " | ".join(cols) + f" | {total} | {', '.join(map(str, wrong)) or '—'} |")
    print("\n(בסוגריים: מספר הציונים)")
    notes = [(n, q, m, s, note) for n, es in per_sheet.items() for q, m, s, note in es if note]
    if notes:
        print("\nהערות שכתבת:")
        for n, q, m, s, note in notes:
            print(f"  [{names[n]}] שאלה {q} — {m}: {note}" + (f" (ציון {s:g})" if s is not None else ""))


if __name__ == "__main__":
    if "--score" in sys.argv:
        score()
    else:
        build(SHEETS["short" if "--short" in sys.argv else "full"])
