@echo off
if not "%1"=="--no-docker" (
  where docker >nul 2>nul
  if not errorlevel 1 (
    echo Starting ZoneApp and TimescaleDB with Docker...
    docker compose up --build
    exit /b %errorlevel%
  )
)
if not exist backend\.env (
  echo Non-Docker mode needs PostgreSQL or TimescaleDB.
  echo Copy backend\.env.example to backend\.env and configure it first.
  exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r backend\requirements.txt
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
