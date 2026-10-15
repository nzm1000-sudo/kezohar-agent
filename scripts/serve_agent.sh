#!/bin/zsh
# Start one always-on service: agent | gateway | tunnel. Used by the LaunchAgents in ~/Library/LaunchAgents.
cd "$(dirname "$0")/.."
export LLM_BASE_URL=http://127.0.0.1:1234/v1
export EMBEDDINGS_PROVIDER=openai-compatible-local EMBEDDINGS_MODEL=text-embedding-bge-m3 EMBEDDINGS_DIMENSIONS=1024
export EMBEDDINGS_REVISION=bge-m3-q8-plain EMBEDDINGS_NORMALIZATION=raw-text-v1 EMBEDDINGS_BASE_URL=http://127.0.0.1:1234/v1
case "$1" in
  agent)   exec .venv/bin/python -B scripts/demo.py ;;
  gateway) exec .venv/bin/python -B scripts/public_gateway.py ;;
  tunnel)  exec /opt/homebrew/bin/cloudflared tunnel run kezohar-agent ;;
  *) echo "usage: $0 agent|gateway|tunnel" >&2; exit 2 ;;
esac
