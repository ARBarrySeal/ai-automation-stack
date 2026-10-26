@echo off
REM Claude Relay launcher. Reads ANTHROPIC_API_KEY from .env via _env.py
REM (claude_relay.py imports _env which loads .env into os.environ on startup).
REM Binds 0.0.0.0 so Docker containers can reach it via host.docker.internal.
REM Do not port-forward 7777 on your router: the relay has no auth.
set "SCRIPT_DIR=%~dp0"
set "PY=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"
cd /d "%SCRIPT_DIR%"
echo Starting Claude Relay on port 7777...
"%PY%" -m uvicorn claude_relay:app --host 0.0.0.0 --port 7777 --log-level warning
