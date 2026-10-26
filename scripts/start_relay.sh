#!/usr/bin/env bash
# Claude Relay launcher (Mac/Linux). Windows: start_relay.bat
# Binds 0.0.0.0 so Docker containers can reach it via host.docker.internal.
# Do not expose port 7777 to the internet: the relay has no auth.
set -euo pipefail
cd "$(dirname "$0")"
PY=../.venv/bin/python; [ -x "$PY" ] || PY=python3
echo "Starting Claude Relay on port 7777..."
exec "$PY" -m uvicorn claude_relay:app --host 0.0.0.0 --port 7777 --log-level warning
