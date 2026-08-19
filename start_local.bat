@echo off
REM ============================================================
REM  Zone Levels - local start (Windows)
REM
REM  1. Put your bars CSV in this folder and name it  data.csv
REM     (TradingView -> right click chart -> Export chart data)
REM  2. Double-click this file.
REM
REM  First run takes a couple of minutes (it builds a venv).
REM  After that it starts in a few seconds.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ==== Zone Levels - local ====
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ from python.org
  echo IMPORTANT: tick "Add Python to PATH" during install.
  pause
  exit /b 1
)

if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
)

echo Installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r backend\requirements.txt --quiet

set ZONEAPP_API_KEY=1380916c63c88e4305b7fb5009964a156b342c394edfbccf03
set ZONEAPP_DB=%~dp0data\local.duckdb
set ZONEAPP_UPLOADS=%~dp0data\uploads
set ZONEAPP_SYMBOL=NSE:NIFTY50-INDEX

if not exist data mkdir data

if exist data.csv (
  if not exist "%ZONEAPP_DB%" (
    echo.
    echo Loading history from data.csv ...
    python scripts\seed.py data.csv
  )
) else (
  echo.
  echo NOTE: no data.csv found in this folder.
  echo The app will start empty. Put your CSV here as data.csv and
  echo restart, or upload it later from the dashboard.
)

echo.
echo ============================================================
echo   Dashboard : http://127.0.0.1:8000
echo   API docs  : http://127.0.0.1:8000/docs
echo   API key   : local-dev-key
echo.
echo   Press Ctrl+C in this window to stop.
echo ============================================================
echo.

start "" http://127.0.0.1:8000
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
