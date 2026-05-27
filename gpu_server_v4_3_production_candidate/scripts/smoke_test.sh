#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8008}"
echo "Health"
curl -s "$BASE/health" | python3 -m json.tool

echo "Detection policy"
curl -s "$BASE/api/detection-policy" | python3 -m json.tool

echo "Dataset summary"
curl -s "$BASE/api/dataset/summary" | python3 -m json.tool
