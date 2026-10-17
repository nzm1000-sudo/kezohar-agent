#!/bin/zsh
# Round three of the answer bank (owner, 2026-10-17: "many thousands"): kashrut answered again from הכשרות למעשה, twelve
# subtopics per subject for new questions, their answers, then the agent reloads and the app's question list is refreshed.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export LLM_BASE_URL=http://127.0.0.1:1234/v1 EMBEDDINGS_PROVIDER=openai-compatible-local EMBEDDINGS_MODEL=text-embedding-bge-m3 \
  EMBEDDINGS_DIMENSIONS=1024 EMBEDDINGS_REVISION=bge-m3-q8-plain EMBEDDINGS_NORMALIZATION=raw-text-v1 EMBEDDINGS_BASE_URL=http://127.0.0.1:1234/v1
log() { echo "$(date '+%F %T') $*" >> data/store/overnight.log; }
log "round 3 started"
.venv/bin/python -B scripts/build_qa_bank.py rekashrut >> data/store/qa-bank/rekashrut.log 2>&1
log "kashrut answered from the book: $(tail -1 data/store/qa-bank/rekashrut.log)"
.venv/bin/python -B scripts/build_qa_bank.py subtopics >> data/store/qa-bank/subtopics.log 2>&1
log "subtopic questions: $(wc -l < data/store/qa-bank/questions.jsonl) total"
.venv/bin/python -B scripts/build_qa_bank.py answers >> data/store/qa-bank/answers.log 2>&1
log "bank round 3 done: $(wc -l < data/store/qa-bank/answers.jsonl) answered"
.venv/bin/python -B scripts/export_bank_questions.py ~/Desktop/kazzohar-harakia-agent/public/data/rav-bari-questions.json >> data/store/overnight.log 2>&1
launchctl kickstart -k gui/$(id -u)/com.kezohar.agent; log "agent reloaded — round 3 done"
