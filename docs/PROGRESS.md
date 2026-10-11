# התקדמות

## הושלם
- [x] אימות LM Studio ב-http://192.168.68.55:1234 (מודל qwen/qwen3.5-35b-a3b זמין), עדכון .env מקומי
- [x] בדיקת בסיס בנצ'מרק 3f545fe (31 בדיקות עוברות, אומתו שוב)
- [x] ענף feature/kezohar-agent-core
- [x] config — קריאת LLM_BASE_URL מ-.env ללא הדפסת סודות
- [x] hebrew — נרמול עברית לחיפוש (ניקוד/טעמים/סופיות/גרש), טקסט מקורי נשמר
- [x] models + ingest — קליטת מקורות, רישיונות (data/licenses.json), מניעת כפילויות, המשכיות, חסימת ילקוט יוסף/חזון עובדיה
- [x] bm25 — מנוע חיפוש מילולי מקומי (stdlib בלבד)
- [x] vector (Mock) + hybrid (RRF k=60) — ממשק מודולרי; Qdrant/BGE-M3 אמיתי ב-NAS בשלב פריסה
- [x] citations — אימות ציטוטים (Validity/Relevance/Support מופרדים)
- [x] fastpath — זמנים/לוח עברי/פרשה ללא LLM (נתיבות כברירת מחדל + פרמטר מיקום, שיטה מצוינת תמיד)
- [x] תיקון ניתוב: שמות חגים מפעילים Fast רק עם "מתי" — שאלה הלכתית (למשל סדר הדלקת נרות חנוכה) מגיעה ל-retrieval
- [x] llm — לקוח OpenAI-compatible ל-LM Studio + נפילה ל"מצב חיפוש" כשה-Mac כבוי
- [x] agent — תזמור: fastpath -> retrieval -> קריאת LLM אחת -> בדיקת בטיחות + cache
- [x] api — FastAPI: GET /health, POST /search, POST /ask (+SSE), validation, rate-limit, cache
- [x] sefaria — מחבר ייבוא עם בדיקת רישיון וחסימת יצירות מוגנות
- [x] e2e — כל 18 התרחישים (סעיף 16) עוברים
- [x] perf — מדידות אמיתיות: BM25 ~0.02ms, היברידי ~0.1ms, fast ~1ms, תשובות LLM מלאות 3-5s
- [x] Docker/compose + scripts/backup+restore

## בתהליך
- כלום — הליבה הושלמה ונבדקה

## חסום / נדחה לפריסה ב-NAS
- Qdrant אמיתי + BGE-M3 על CPU של NAS — ממשק Mock מוכן, מדידה אמיתית תתבצע כשחומרת NAS זמינה
- ייבוא Sefaria מלא (כל 4 חלקי שו"ע) — מחבר מוכן ונבדק, ההרצה המלאה תתבצע בפריסה
- פריסת Docker ל-NAS — קבצים מוכנים, לא הופעלו שירותים (אין גישה ל-NAS מהסשן הזה)

## הצעד הבא (לסוכן/סשן חדש)
1. `git log --oneline -5` — לוודא שהענף feature/kezohar-agent-core מעודכן
2. `.venv/bin/python -m pytest tests/ bench/test_run_reliability.py -q` — לוודא 111+31 עוברים
3. הרצת ייבוא Sefaria מלא: `.venv/bin/python -m kezohar.sefaria ...` ואז ingest ל-store
4. פריסה ל-NAS: rsync + `docker compose up` (פורט 8710, רשת kezohar-net)
5. מדידת NAS Benchmark אמיתית (Qdrant/BGE-M3 על CPU)
