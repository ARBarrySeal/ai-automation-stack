@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

echo.
echo ============================================================
echo  mcpo MCP Bridge  -  port 8000
echo ============================================================
echo  Servers: whatever is listed in mcpo\config.json
echo ============================================================
echo  Rendering config.rendered.json from .env...
python "%SCRIPT_DIR%render_config.py"
if errorlevel 1 (
    echo Failed to render config. Check .env has every key config.json uses.
    exit /b 1
)
echo  Open WebUI connects via http://host.docker.internal:8000/
echo  Press Ctrl+C to stop.
echo.

uvx mcpo --config "%SCRIPT_DIR%config.rendered.json" --port 8000
