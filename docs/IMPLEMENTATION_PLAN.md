# תוכנית מימוש — Kezohar Agent

## רכיבים וסדר
1. `config` — קריאת LLM_BASE_URL מ-.env (ללא הדפסת סודות)
2. `hebrew` — נרמול עברית לחיפוש (שמירת מקור)
3. `models` + `ingest` — קליטת מקורות, רישיונות, מזהים יציבים, המשכיות
4. `bm25` — חיפוש מילולי מקומי
5. `vector` + `hybrid` — ממשק embeddings + מיזוג RRF
6. `citations` — אימות ציטוטים (Validity/Relevance/Support)
7. `fastpath` — זמנים/לוח ללא LLM (נתיבות כברירת מחדל + פרמטר מיקום)
8. `llm` — לקוח OpenAI-compatible ל-LM Studio + נפילה למקורות בלבד
9. `agent` — תזמור: fastpath -> retrieval -> llm -> safety
10. `api` — FastAPI: GET /health, POST /search, POST /ask (+SSE)
11. Docker/compose, scripts/backup+restore
12. בדיקות E2E + מדידת ביצועים

## תלויות
- חובה: stdlib בלבד לליבה (hebrew/bm25/citations/fastpath-basic/llm/ingest).
- רשות: fastapi, uvicorn, pytest, httpx, pyluach, astral — בסביבת venv בלבד.
- Qdrant אמיתי — רק ב-NAS; מקומית Mock.

## בדיקות
- `tests/test_*.py` לכל רכיב + `tests/test_e2e_*.py` ל-18 התרחישים.
- סף: כל בדיקה חייבת לעבור לפני Commit.

## מדדי הצלחה
- חיפוש ראשוני < 1s (נמדד), תשובה מלאה ≤ 5s (נמדד מול LM Studio), זמנים < 1s.
- אין פסיקה ללא מקור; אין מראה מקום מומצא (נבדק עם מקורות מטעים).

## סיכונים / פתוח
- Python מערכת 3.9 בלבד — נצמד ל-syntax תואם 3.9.
- Qdrant/NAS לא זמין כאן — ממשק Mock + תיעוד פריסה.
- טקסטים מוגנים (ילקוט יוסף/חזון עובדיה) — לא מייבאים ללא רישיון.
