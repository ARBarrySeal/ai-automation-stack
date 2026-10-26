#!/usr/bin/env bash
# mcpo MCP bridge on port 8000 (Mac/Linux). Windows: start.bat
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Rendering config.rendered.json from .env..."
python3 "$HERE/render_config.py"
echo "Open WebUI connects via http://host.docker.internal:8000/  (Ctrl+C to stop)"
exec uvx mcpo --config "$HERE/config.rendered.json" --port 8000
