"""Blind Hebrew-quality review sheet.

  python3 bench/hebrew_review.py           -> bench/hebrew-review.md (answers labelled A, B, C...)
                                              bench/hebrew-review-key.json (letter -> model, per question)
  python3 bench/hebrew_review.py --score   -> reads the filled-in scores, prints average per model

Answers are cut at a leaked chat token ("<|..."), which would otherwise identify the model.
Letters are reshuffled for every question (fixed seed) so a model can't be recognised
by position. Only questions that got an LLM answer are included ([fast] ones are not).
"""
import json, random, re, statistics, sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
SHEET = BENCH / "hebrew-review.md"
KEY = BENCH / "hebrew-review-key.json"
SCORE_LINE = "ציון עברית (1-5):"


def build():
    if SHEET.exists() and re.search(rf"{re.escape(SCORE_LINE)}\*\*\s*[1-5]", SHEET.read_text()):
        raise SystemExit(f"{SHEET.name} already has scores — not overwriting. Move it aside first.")
    runs = [json.loads(p.read_text()) for p in sorted((BENCH / "raw").glob("*.json"))]
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
    for i, q in enumerate(runs[0]["questions"]):
        if "answer" not in q:
            continue
        order = list(range(len(runs)))
        rng.shuffle(order)
        key[str(q["n"])] = {letters[j]: runs[m]["model"] for j, m in enumerate(order)}
        out += ["---", "", f"## שאלה {q['n']}: {q['q']}", ""]
        for j, m in enumerate(order):
            ans = runs[m]["questions"][i]["answer"]["answer"].split("<|")[0].strip() or "(ריק)"
            out += [f"### {letters[j]}", "", "> " + ans.replace("\n", "\n> "), "", f"**{SCORE_LINE}** ", ""]
    SHEET.write_text("\n".join(out) + "\n")
    KEY.write_text(json.dumps(key, ensure_ascii=False, indent=1))
    print(f"wrote {SHEET.name} ({len(key)} questions, {len(runs)} models) and {KEY.name}")


def score():
    key = json.loads(KEY.read_text())
    scores, q, letter = {}, None, None
    for line in SHEET.read_text().splitlines():
        if m := re.match(r"## שאלה (\d+):", line):
            q = m[1]
        elif m := re.match(r"### ([A-J])\s*$", line):
            letter = m[1]
        elif SCORE_LINE in line and q and letter:
            if d := re.search(r"[1-5]", line.split(SCORE_LINE, 1)[1]):
                scores.setdefault(key[q][letter], []).append(int(d[0]))
    if not scores:
        print("לא נמצאו ציונים בקובץ.")
    for model, s in sorted(scores.items(), key=lambda kv: -statistics.mean(kv[1])):
        print(f"{statistics.mean(s):.2f}  ({len(s)} ציונים)  {model}")


if __name__ == "__main__":
    score() if "--score" in sys.argv else build()
