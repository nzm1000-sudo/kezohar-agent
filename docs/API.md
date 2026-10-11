# API

## GET /health
בודק תקינות + זמינות LLM (לא מבצע unload, לא משנה מודלים).
```json
{"status": "ok", "llm_ok": true, "llm_models": ["qwen/qwen3.5-35b-a3b", "..."], "store_docs": 15}
```

## POST /search
```json
{"query": "אורז", "top_k": 5}
```
תשובה: `{"results": [{"source_id","work_title","reference","text","license","tradition","score","backend"}]}`.
ספרדים תחילה (tradition=sephardi קודם).

## POST /ask
```json
{"question": "...", "top_k": 5, "lat": 31.42, "lon": 34.59, "location": "נתיבות", "stream": false}
```
תשובה: `{"answer","sources","verdict","mode","elapsed_s"}`.
- `mode=fast` — חישוב קוד בלבד, ללא LLM.
- `mode=llm` — תשובה מהמודל על סמך מקורות + אימות ציטוט.
- `mode=sources-only` — ה-Mac כבוי ("מצב חיפוש"): מקורות בלבד.
- `mode=llm-guarded` — הציטוט לא אומת: מוחזר "אין לי מקור לכך" + מראי מקום.
- `stream=true` — SSE: אירוע `sources` תחילה, אחר כך `answer` למשפט, ולבסוף `done`.
- שגיאות: 400 (שאלה חסרה/ארוכה/JSON פגום), 429 (rate limit).
