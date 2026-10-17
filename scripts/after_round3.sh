#!/bin/zsh
# After round three: every new answer is checked, then the app's question list and the agent are refreshed.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
log() { echo "$(date '+%F %T') $*" >> data/store/overnight.log; }
while pgrep -f "overnight_bank_round3.sh" >/dev/null; do sleep 120; done
.venv/bin/python -B scripts/build_qa_bank.py verify >> data/store/qa-bank/verify.log 2>&1
log "checked: $(tail -1 data/store/qa-bank/verify.log)"
.venv/bin/python -B scripts/export_bank_questions.py ~/Desktop/kazzohar-harakia-agent/public/data/rav-bari-questions.json >> data/store/overnight.log 2>&1
launchctl kickstart -k gui/$(id -u)/com.kezohar.agent; log "agent reloaded with checked answers only"
