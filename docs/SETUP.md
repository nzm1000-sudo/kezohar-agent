# הוראות הפעלה (SETUP)

## דרישות
- Python 3.9+ (נבדק על 3.9 מערכת + venv)
- LM Studio עם שרת OpenAI-compatible (פורט 1234)

## התקנה מקומית
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
printf 'LLM_BASE_URL=http://<MAC_LAN_IP>:1234/v1\n' > .env
```

## קליטת מקורות לדוגמה
```bash
.venv/bin/python - <<'PY'
import json, sys
sys.path.insert(0, "src")
from kezohar import ingest
raws = json.loads(open("data/sample_sources/sources.json", encoding="utf-8").read())
print(ingest.ingest_sources(raws, "data/store/sources.jsonl", progress_path="data/store/progress.json"))
PY
```

## הרצת API
```bash
STORE_PATH=data/store/sources.jsonl .venv/bin/python -m uvicorn kezohar.api:app --host 0.0.0.0 --port 8710 --app-dir src
# בדיקה:
curl localhost:8710/health
curl -X POST localhost:8710/ask -H 'Content-Type: application/json' -d '{"question":"מתי שקיעה היום בנתיבות?"}'
```

## Docker (פריסה עתידית ב-NAS)
```bash
docker compose up --build
```
פורט 8710, רשת kezohar-net. לא להפעיל שירותים קיימים ולא לגעת בקונטיינרים אחרים.
