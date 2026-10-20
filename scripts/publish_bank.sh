#!/bin/zsh
# The bank's checked answers to the app, with the catalog kept whole (owner's standing rule, 2026-10-20: every new question
# gets its subject): export the bank → list every question → assign the new ones → export the catalog. Then PR as usual.
set -e
APP=~/Desktop/kazzohar-harakia-agent
cd ~/kezohar-agent
set -a; . ./.env; set +a
python3 scripts/export_bank_questions.py $APP/public/data/rav-bari-questions.json
node $APP/scripts/dump-questions.mjs data/store/all-questions.json
.venv/bin/python -B scripts/question_taxonomy.py update
.venv/bin/python -B scripts/question_taxonomy.py export $APP/public/data/question-taxonomy.json
