#!/bin/bash
# Restore agent data (test env only — verify before touching real data)
set -euo pipefail
F="${1:?usage: restore.sh <backup.tgz|jsonl>}"
if [[ "$F" == *.jsonl ]]; then
  cp "$F" data/store/sources.jsonl
else
  docker run --rm -v kezohar-agent_agent-data:/data -v "$PWD:/b" alpine tar xzf "/b/$F" -C /
fi
echo "restored from $F"
