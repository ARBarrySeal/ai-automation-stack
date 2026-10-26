@echo off
REM One-click Docker engine recovery. Right-click > Run as administrator
REM (admin lets it restart the com.docker.service Windows service too).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix-docker-engine.ps1"
echo.
pause
