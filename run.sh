#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
exec python3 -m uvicorn server:app \
  --host 127.0.0.1 \
  --port 8787 \
  --reload \
  --limit-concurrency 64 \
  --backlog 128 \
  --timeout-keep-alive 5 \
  --no-server-header
