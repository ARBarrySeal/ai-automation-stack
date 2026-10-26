#!/usr/bin/env bash
PY="$(dirname "$0")/../.venv/bin/python"; [ -x "$PY" ] || PY=python3
exec "$PY" "$(dirname "$0")/smart.py" "$@"
