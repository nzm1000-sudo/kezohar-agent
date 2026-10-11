FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/kezohar/ ./kezohar/
COPY data/licenses.json ./data/licenses.json
COPY data/claim_reformulations.json ./data/claim_reformulations.json
ENV PYTHONPATH=/app STORE_PATH=/data/sources.jsonl AGENT_PORT=8710
EXPOSE 8710
CMD ["uvicorn", "kezohar.api:app", "--host", "0.0.0.0", "--port", "8710"]
