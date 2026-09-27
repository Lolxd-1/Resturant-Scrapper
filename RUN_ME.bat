@echo off
setlocal
title Menu Studio
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Menu Studio could not start. Read the message above, fix it, then double-click RUN_ME.bat again.
pause
exit /b 1
