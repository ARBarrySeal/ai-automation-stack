@echo off
:: Run this once as Administrator to register mcpo as a Windows startup task.
:: mcpo will then start automatically when you log in.

set "TASK_NAME=mcpo-mcp-bridge"
set "SCRIPT_DIR=%~dp0"

echo Registering "%TASK_NAME%" in Windows Task Scheduler...

schtasks /Create /TN "%TASK_NAME%" /TR "\"%SCRIPT_DIR%start.bat\"" /SC ONLOGON /RU "%USERNAME%" /F /RL HIGHEST /DELAY 0001:00

if %ERRORLEVEL%==0 (
    echo.
    echo SUCCESS: mcpo will now start automatically at login.
    echo To remove: schtasks /Delete /TN "%TASK_NAME%" /F
) else (
    echo.
    echo ERROR: Could not register task. Run this script as Administrator.
)
pause
