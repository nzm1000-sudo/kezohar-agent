#!/bin/zsh
# After round three: every answer is checked; rejected answers are answered again and checked again (twice); then the
# app's question list and the agent are refreshed. A question is never dropped — only its answer is redone.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export LLM_BASE_URL=http://127.0.0.1:1234/v1 EMBEDDINGS_PROVIDER=openai-compatible-local EMBEDDINGS_MODEL=text-embedding-bge-m3 \
  EMBEDDINGS_DIMENSIONS=1024 EMBEDDINGS_REVISION=bge-m3-q8-plain EMBEDDINGS_NORMALIZATION=raw-text-v1 EMBEDDINGS_BASE_URL=http://127.0.0.1:1234/v1
log() { echo "$(date '+%F %T') $*" >> data/store/overnight.log; }
while pgrep -f "overnight_bank_round3.sh|build_qa_bank.py verify" >/dev/null; do sleep 120; done
for pass in 1 2; do
  .venv/bin/python -B scripts/build_qa_bank.py verify >> data/store/qa-bank/verify.log 2>&1
  log "checked (pass $pass): $(tail -1 data/store/qa-bank/verify.log)"
  .venv/bin/python -B scripts/build_qa_bank.py repair >> data/store/qa-bank/repair.log 2>&1
  log "redone (pass $pass): $(tail -1 data/store/qa-bank/repair.log)"
done
.venv/bin/python -B scripts/build_qa_bank.py verify >> data/store/qa-bank/verify.log 2>&1
.venv/bin/python -B scripts/export_bank_questions.py ~/Desktop/kazzohar-harakia-agent/public/data/rav-bari-questions.json >> data/store/overnight.log 2>&1
launchctl kickstart -k gui/$(id -u)/com.kezohar.agent; log "agent reloaded — checked and redone answers"
