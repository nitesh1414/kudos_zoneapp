@echo off
where docker >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is required. Install it, then run this file again.
  exit /b 1
)
echo Starting ZoneApp and TimescaleDB...
docker compose up --build
