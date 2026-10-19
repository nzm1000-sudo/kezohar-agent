#!/bin/zsh
# The subjects the bank had none of (build_qa_bank.NEW_TOPICS): questions, answers, check, redo, check again — after
# whatever bank run is going on now. Each step's last line goes to data/store/overnight.log.
cd ~/kezohar-agent
set -a; . ./.env; set +a
export LLM_BASE_URL=http://127.0.0.1:1234/v1 EMBEDDINGS_PROVIDER=openai-compatible-local EMBEDDINGS_MODEL=text-embedding-bge-m3 \
  EMBEDDINGS_DIMENSIONS=1024 EMBEDDINGS_REVISION=bge-m3-q8-plain EMBEDDINGS_NORMALIZATION=raw-text-v1 EMBEDDINGS_BASE_URL=http://127.0.0.1:1234/v1
log() { echo "$(date '+%F %T') $*" >> data/store/overnight.log; }
while pgrep -f "build_qa_bank.py|books_answers.sh" >/dev/null; do sleep 120; done
TOPICS=("${(@f)$(.venv/bin/python -B -c 'import sys;sys.path.insert(0,"scripts");import build_qa_bank as b;print("\n".join(b.NEW_TOPICS))')}")
.venv/bin/python -B scripts/build_qa_bank.py questions --topics "${TOPICS[@]}" >> data/store/qa-bank/answers.log 2>&1; log "new topics asked: $(tail -1 data/store/qa-bank/answers.log)"
.venv/bin/python -B scripts/build_qa_bank.py answers >> data/store/qa-bank/answers.log 2>&1; log "new topics answered: $(tail -1 data/store/qa-bank/answers.log)"
.venv/bin/python -B scripts/build_qa_bank.py verify >> data/store/qa-bank/verify.log 2>&1; log "new topics checked: $(tail -1 data/store/qa-bank/verify.log)"
.venv/bin/python -B scripts/build_qa_bank.py repair >> data/store/qa-bank/repair.log 2>&1; log "new topics redone: $(tail -1 data/store/qa-bank/repair.log)"
.venv/bin/python -B scripts/build_qa_bank.py verify >> data/store/qa-bank/verify.log 2>&1; log "new topics checked again: $(tail -1 data/store/qa-bank/verify.log)"
