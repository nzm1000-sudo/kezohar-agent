# בדיקות

הרצה:
```bash
.venv/bin/python -m pytest tests/ bench/test_run_reliability.py -q
```

- `tests/test_hebrew.py` — נרמול (ניקוד, סופיות, גרש, מראי מקום).
- `tests/test_ingest.py` — רישיונות, כפילויות, המשכיות, חסימת מוגנים.
- `tests/test_bm25.py` — איכות חיפוש על שאלות bench.
- `tests/test_hybrid.py` — מיזוג RRF (k=60).
- `tests/test_citations.py` — ציטוט תקין/מומצא/לא רלוונטי/ללא מקור/מחוץ לתחום.
- `tests/test_fastpath.py` — זמנים/פרשה/תאריך/מיקום/סירוב.
- `tests/test_llm.py` — בניית הודעות, נפילה כשהשרת כבוי (Mock, לא הרסני).
- `tests/test_agent.py` — תזמור, cache, ספרדים תחילה.
- `tests/test_api.py` — health/search/ask/SSE/שגיאות/מקביליות/חזרות.
- `tests/test_e2e.py` — 18 תרחישי סעיף 16.
- `tests/test_sefaria.py` — חסימת מוגנים, מיפוי רישיון.
- `bench/test_run_reliability.py` — 31 בדיקות תשתית בנצ'מרק (קיימות).

מדידות אמיתיות (לא Mock): `STORE_PATH=data/store/sources.jsonl .venv/bin/python scripts/perf.py`.
אין לדווח Mock כביצועים אמיתיים.
