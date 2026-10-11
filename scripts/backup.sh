#!/bin/bash
# Backup agent data volume + store (test env first, never prod data blindly)
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)
cp data/store/sources.jsonl "$BACKUP_DIR/sources-$TS.jsonl" 2>/dev/null || echo "no local store"
docker run --rm -v kezohar-agent_agent-data:/data -v "$PWD/$BACKUP_DIR:/b" alpine tar czf "/b/agent-data-$TS.tgz" /data || echo "volume backup skipped (no docker/volume)"
echo "backup -> $BACKUP_DIR ($TS)"
