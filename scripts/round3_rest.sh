#!/bin/zsh
# The rest of round three after the switch to three questions at a time (2026-10-17): answers, then check and redo.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export LLM_BASE_URL=http://127.0.0.1:1234/v1 EMBEDDINGS_PROVIDER=openai-compatible-local EMBEDDINGS_MODEL=text-embedding-bge-m3 \
  EMBEDDINGS_DIMENSIONS=1024 EMBEDDINGS_REVISION=bge-m3-q8-plain EMBEDDINGS_NORMALIZATION=raw-text-v1 EMBEDDINGS_BASE_URL=http://127.0.0.1:1234/v1
echo "$(date '+%F %T') answers resumed, three at a time" >> data/store/overnight.log
.venv/bin/python -B scripts/build_qa_bank.py answers >> data/store/qa-bank/answers.log 2>&1
echo "$(date '+%F %T') bank round 3 answers done: $(wc -l < data/store/qa-bank/answers.jsonl)" >> data/store/overnight.log
exec scripts/after_round3.sh
