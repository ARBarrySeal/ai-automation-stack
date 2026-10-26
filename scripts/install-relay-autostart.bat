@echo off
set "TASK_NAME=claude-relay"
set "SCRIPT_DIR=%~dp0"

echo Registering "%TASK_NAME%" in Windows Task Scheduler...

schtasks /Create /TN "%TASK_NAME%" /TR "\"%SCRIPT_DIR%start_relay.bat\"" /SC ONLOGON /RU "%USERNAME%" /F /RL HIGHEST /DELAY 0001:30

if %ERRORLEVEL%==0 (
    echo SUCCESS: claude-relay will start automatically at login.
    echo To remove: schtasks /Delete /TN "%TASK_NAME%" /F
) else (
    echo ERROR: Run as Administrator.
)
pause
