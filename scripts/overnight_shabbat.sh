#!/bin/zsh
# Unattended work over Shabbat (owner, 2026-10-16): the answer bank grows, Wikipedia joins the meaning index,
# the agent reloads to use them. Each step waits for the previous one; nothing here touches the app or the site.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export LLM_BASE_URL=http://127.0.0.1:1234/v1 EMBEDDINGS_PROVIDER=openai-compatible-local EMBEDDINGS_MODEL=text-embedding-bge-m3 \
  EMBEDDINGS_DIMENSIONS=1024 EMBEDDINGS_REVISION=bge-m3-q8-plain EMBEDDINGS_NORMALIZATION=raw-text-v1 EMBEDDINGS_BASE_URL=http://127.0.0.1:1234/v1
log() { echo "$(date '+%F %T') $*" >> data/store/overnight.log; }
while pgrep -f "build_qa_bank.py answers" >/dev/null; do sleep 120; done
log "bank round 1 done: $(wc -l < data/store/qa-bank/answers.jsonl) answered"
launchctl kickstart -k gui/$(id -u)/com.kezohar.agent; log "agent reloaded with the bank"
.venv/bin/python -B scripts/build_qa_bank.py subtopics >> data/store/qa-bank/subtopics.log 2>&1
log "subtopic questions: $(wc -l < data/store/qa-bank/questions.jsonl) total"
.venv/bin/python -B scripts/build_qa_bank.py answers >> data/store/qa-bank/answers.log 2>&1
log "bank round 2 done: $(wc -l < data/store/qa-bank/answers.jsonl) answered"
while pgrep -f "import_wikipedia_judaism.py" >/dev/null; do sleep 120; done
log "wikipedia import done"
nice -n 15 .venv/bin/python -B scripts/build_vector_index.py data/store/user-library/library.sqlite3 >> data/store/overnight.log 2>&1
log "meaning index updated"
launchctl kickstart -k gui/$(id -u)/com.kezohar.agent; log "agent reloaded — all done"
