#!/usr/bin/env bash
set -euo pipefail
MODEL="${1:-gemma4:e4b}"
echo "Pulling Ollama model: $MODEL"
ollama pull "$MODEL"
ollama list | grep -E "$(echo "$MODEL" | cut -d: -f1)|NAME" || true
