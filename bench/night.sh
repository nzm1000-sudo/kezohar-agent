#!/bin/bash
# Re-run the benchmark for the leading models on an idle Mac (e.g. overnight).
#   bash ~/kezohar-agent/bench/night.sh [model ...]
# Waits (up to 3 h) until the Mac is quiet, keeps it awake while running, writes
# bench/raw-night-<date>/ + bench/results-night-<date>.md, and commits them.
# Requirements: LM Studio open with its server on, Mac plugged in, lid open.
set -euo pipefail
cd "$(dirname "$0")/.."

MODELS=("$@")
[ ${#MODELS[@]} -eq 0 ] && MODELS=(qwen/qwen3.5-35b-a3b google/gemma-4-26b-a4b)
STAMP=$(date +%Y%m%d)
OUT="raw-night-$STAMP"
LOG="bench/night-$STAMP.log"
MAX_LOAD=2.0

exec > >(tee -a "$LOG") 2>&1
echo "$(date '+%F %H:%M') מתחיל. מודלים: ${MODELS[*]}"

BASE=$(grep '^LLM_BASE_URL=' .env | cut -d= -f2-)
curl -sf -m 5 "$BASE/models" >/dev/null || { echo "❌ שרת LM Studio לא עונה ב-$BASE — פתח את LM Studio והפעל את השרת."; exit 1; }

for i in $(seq 1 180); do
  load=$(sysctl -n vm.loadavg | awk '{print $2}')
  awk "BEGIN{exit !($load < $MAX_LOAD)}" && break
  [ "$i" -eq 1 ] || [ $((i % 15)) -eq 0 ] && echo "$(date +%H:%M) המחשב עסוק (עומס $load), מחכה..."
  sleep 60
done
echo "$(date +%H:%M) עומס $load — מתחיל מדידה (העומס נרשם בדוח בכל מקרה)."

caffeinate -i -m python3 bench/run.py --out "$OUT" "${MODELS[@]}"
python3 bench/report.py --raw "$OUT" --out "results-night-$STAMP.md"

git add "bench/$OUT" "bench/results-night-$STAMP.md" "$LOG"
git commit -qm "Night benchmark $STAMP: ${MODELS[*]}" && echo "✅ נשמר ב-git."
echo "$(date '+%F %H:%M') סיום. הדוח: bench/results-night-$STAMP.md"
