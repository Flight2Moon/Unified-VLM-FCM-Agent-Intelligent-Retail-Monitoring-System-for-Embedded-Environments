#!/usr/bin/env bash
set -euo pipefail
PROFILE="${1:-low_vram}"   # low_vram | cpu | cuda | api | off
MODE="${2:-prod}"          # prod | dev
export EAGER_RUNTIME_PROFILE="$PROFILE"
CONFIG="${CONFIG:-configs/server_config.yaml}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8008}"
export CONFIG
export EAGER_CONFIG="$CONFIG"

case "$PROFILE" in
  cpu)
    export CUDA_VISIBLE_DEVICES="-1"
    export OLLAMA_PROFILE="cpu"
    ;;
  cuda)
    export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"
    export OLLAMA_PROFILE="cuda"
    export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
    ;;
  low_vram)
    export OLLAMA_PROFILE="low_vram"
    export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
    ;;
  api)
    export OLLAMA_PROFILE="api"
    if [[ -z "${GEMINI_API_KEY:-}" ]]; then
      echo "[WARN] GEMINI_API_KEY is not set. Gemini API calls will fail until you export it." >&2
    fi
    ;;
  off)
    export OLLAMA_PROFILE="off"
    ;;
  *)
    echo "Unknown profile: $PROFILE" >&2
    exit 1
    ;;
esac

if [[ "$MODE" == "dev" ]]; then
  exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
fi
exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" --workers 1
