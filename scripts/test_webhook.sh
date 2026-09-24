#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://127.0.0.1:8000/webhook}"
QUESTION="${2:-Почему небо голубое? Ответь одним коротким предложением.}"

curl --fail-with-body --silent --show-error   --max-time 5   -H 'Content-Type: application/json'   -d "$(python3 -c 'import json,sys; print(json.dumps({"version":"1.0","session":{"new":False,"session_id":"github-test"},"request":{"original_utterance":sys.argv[1]}}, ensure_ascii=False))' "$QUESTION")"   "$URL"
echo
