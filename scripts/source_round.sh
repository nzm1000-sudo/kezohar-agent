#!/bin/zsh
# Questions from the books' own halachot (source_questions.py), judged by the bank's check, then the rejected redone and
# judged again. Each step's last line goes to data/store/overnight.log. Waits for any other bank run first.
cd ~/kezohar-agent
set -a; . ./.env; set +a
export LLM_BASE_URL=http://127.0.0.1:1234/v1 EMBEDDINGS_PROVIDER=openai-compatible-local EMBEDDINGS_MODEL=text-embedding-bge-m3 \
  EMBEDDINGS_DIMENSIONS=1024 EMBEDDINGS_REVISION=bge-m3-q8-plain EMBEDDINGS_NORMALIZATION=raw-text-v1 EMBEDDINGS_BASE_URL=http://127.0.0.1:1234/v1
log() { echo "$(date '+%F %T') $*" >> data/store/overnight.log; }
while pgrep -f "build_qa_bank.py|new_topics.sh" >/dev/null; do sleep 120; done
.venv/bin/python -B scripts/source_questions.py run "$@" >> data/store/source.log 2>&1; log "from the books ($*): $(tail -1 data/store/source.log)"
.venv/bin/python -B scripts/build_qa_bank.py verify >> data/store/qa-bank/verify.log 2>&1; log "books' questions checked: $(tail -1 data/store/qa-bank/verify.log)"
