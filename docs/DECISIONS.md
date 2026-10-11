# החלטות

- שפת API: FastAPI (נימוק: std ל-Python, SSE/validation/health/cache פשוטים, חינמי). אם FastAPI לא מותקן — `api.py` מספק גם שרת fallback מבוסס stdlib.
- BM25: מימוש עצמי ב-stdlib (אפס תלות, בדיק + מהיר לסקאלת בדיקות).
- Embeddings: ממשק `VectorStore`; מימוש `MockVectorStore` לבדיקות; מימוש אמיתי מאוחר יותר עם BGE-M3/Qdrant ב-NAS.
- מיזוג: RRF (k=60) — מתועד ופשוט.
- זמנים: חישוב אסטרונומי בסיסי (זריחה/שקיעה NOAA) + תאריך עברי דרך `pyluach` אם זמין, אחרת fallback מתועד; שיטה הלכתית מצוינת תמיד לצד הזמן.
- מודל: qwen/qwen3.5-35b-a3b, reasoning כבוי — זמני, בכפוף למדידה.
