@echo off
setlocal
title Resturant-Scrapper PROD
cd /d "%~dp0"

echo ============================================================
echo  Resturant-Scrapper PROD v1.0  -  menu Excel in, SmartBiz out
echo ============================================================
echo.

REM ---- 1. Find Python (py launcher preferred, else python) ----
set PY=
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 --version >nul 2>nul
  if %errorlevel%==0 set PY=py -3
)
if not defined PY (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python --version >nul 2>nul
    if %errorlevel%==0 set PY=python
  )
)
if not defined PY (
  echo [ERROR] Python 3.10 or newer was not found on this PC.
  echo.
  echo Do this once: install it from https://www.python.org/downloads/
  echo IMPORTANT: on the first installer screen, tick
  echo            "Add python.exe to PATH", then click Install.
  echo Then double-click RUN_ME again.
  echo.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% --version

REM ---- 2. Sanity: are all repo files present? ----
if not exist "app.py" (
  echo [ERROR] app.py missing. Download the FULL repo ZIP
  echo (Code button -^> Download ZIP) and extract everything, then retry.
  pause
  exit /b 1
)
if not exist "data\pairs.json" (
  echo [ERROR] data\pairs.json missing. Download the FULL repo ZIP
  echo (Code button -^> Download ZIP) and extract everything, then retry.
  pause
  exit /b 1
)
if not exist "data\smartbiz_template.xlsx" (
  echo [ERROR] data\smartbiz_template.xlsx missing. Download the FULL repo ZIP
  echo (Code button -^> Download ZIP) and extract everything, then retry.
  pause
  exit /b 1
)

REM ---- 3. Dependencies (fast after the first run) ----
echo.
echo [1/2] Checking dependencies (first run downloads them, ~2 min)...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERROR] Could not install dependencies. Check your internet and retry.
  pause
  exit /b 1
)

REM ---- 4. Already running? (double-clicked twice, or leftover server) ----
set APPUP=no
for /f %%i in ('powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -TimeoutSec 4).StatusCode } catch { 'down' }"') do set APPUP=%%i
if "%APPUP%"=="200" (
  echo.
  echo App is ALREADY running. Opening it in your browser...
  start "" "http://localhost:8501"
  echo If the page does not load, close other black windows and retry.
  pause
  exit /b 0
)

REM ---- 5. Launch ----
echo.
echo [2/2] Starting the app - a browser tab opens automatically.
echo Keep this window OPEN while you use the app. Close it to stop.
echo If port 8501 is busy, close the other program and double-click again.
echo.
start "" "http://localhost:8501"
%PY% -m streamlit run app.py --server.headless true --server.port 8501 --server.runOnSave false
echo.
echo App stopped. You can close this window.
pause
