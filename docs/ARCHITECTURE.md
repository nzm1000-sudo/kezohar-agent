# ארכיטקטורה

iPhone App -> Agent API (NAS :8710) -> [Fast Path | Hybrid Search (BM25+Qdrant) | LLM Client -> LM Studio (Mac :1234)]

- `api.py` — שכבת HTTP בלבד (validation, SSE, timeouts, logging, rate-limit בסיסי, cache).
- `agent.py` — ניתוב: fastpath קודם; אחרת retrieval בקוד ואז קריאת LLM אחת.
- `hybrid.py` — מיזוג RRF של BM25 + vector; מחזיר id/text/ref/score/license.
- אם Mac כבוי — מחזירים מקורות בלבד ("מצב חיפוש"). Fast Path ממשיך לעבוד.
- שום IP קשיח בקוד — הכול מ-.env (`LLM_BASE_URL`, `AGENT_PORT`, `QDRANT_URL`).
