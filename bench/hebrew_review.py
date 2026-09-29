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


def read_scores(cfg):
    sheet, keyfile = paths(cfg)
    if not (sheet.exists() and keyfile.exists()):
        return {}
    key = json.loads(keyfile.read_text())
    scores, q, letter = {}, None, None
    for line in sheet.read_text().splitlines():
        if m := re.match(r"## שאלה (\d+):", line):
            q = m[1]
        elif m := re.match(r"### ([A-J])\s*$", line):
            letter = m[1]
        elif SCORE_LINE in line and q and letter:
            if d := re.search(r"[1-5]", line.split(SCORE_LINE, 1)[1]):
                scores.setdefault(key[q][letter], []).append(int(d[0]))
    return scores


def score():
    found = False
    for cfg in SHEETS.values():
        scores = read_scores(cfg)
        if not scores:
            continue
        found = True
        print(f"\n{paths(cfg)[0].name}:")
        for model, s in sorted(scores.items(), key=lambda kv: -statistics.mean(kv[1])):
            print(f"  {statistics.mean(s):.2f}  ({len(s)} ציונים)  {model}")
    if not found:
        print("לא נמצאו ציונים באף קובץ דירוג.")


if __name__ == "__main__":
    if "--score" in sys.argv:
        score()
    else:
        build(SHEETS["short" if "--short" in sys.argv else "full"])
