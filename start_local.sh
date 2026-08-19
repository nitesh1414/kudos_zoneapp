#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v docker >/dev/null; then
  echo "Docker is required. Install Docker Desktop/Engine, then rerun this script."
  exit 1
fi
echo "Starting ZoneApp and TimescaleDB..."
docker compose up --build
