#!/usr/bin/env bash
# Install the daily market-close cron for this checkout.
#
# The endpoint it calls is idempotent and skips weekends and rows in
# market_holidays, so retries can never duplicate a completed run. It covers
# every tracked symbol in one call.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ZONEAPP_ENV_FILE:-${PROJECT_DIR}/backend/.env}"
BASE_URL="${ZONEAPP_BASE_URL:-http://127.0.0.1:8000}"
LOG_DIR="${PROJECT_DIR}/logs"
CRON_LOG="${LOG_DIR}/market-close.log"
HEALTH_LOG="${LOG_DIR}/health-check.log"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="$(command -v python3)"
mkdir -p "$LOG_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo "[setup_cron] $ENV_FILE not found. Copy backend/.env.example first." >&2
  exit 1
fi
if ! grep -q '^ZONEAPP_API_KEY=' "$ENV_FILE"; then
  echo "[setup_cron] ZONEAPP_API_KEY must be set in $ENV_FILE (the job authenticates with it)." >&2
  exit 1
fi

TAG="# ZONEAPP_MARKET_CLOSE"
JOB="0 17 * * 1-5 set -a; . ${ENV_FILE}; set +a; curl --retry 3 --retry-delay 60 --fail-with-body -X POST ${BASE_URL}/api/jobs/market-close -H \"X-API-Key: \${ZONEAPP_API_KEY}\" >> ${CRON_LOG} 2>&1 ${TAG}"
HEALTH_TAG="# ZONEAPP_HEALTH_CHECK"
HEALTH_JOB="20 17 * * 1-5 set -a; . ${ENV_FILE}; set +a; cd ${PROJECT_DIR} && ${PYTHON_BIN} scripts/health_check.py >> ${HEALTH_LOG} 2>&1 ${HEALTH_TAG}"

CURRENT="$(crontab -l 2>/dev/null | grep -v "${TAG}" | grep -v "${HEALTH_TAG}" || true)"
printf '%s\n%s\n%s\n%s\n' "CRON_TZ=Asia/Kolkata" "${CURRENT}" "${JOB}" "${HEALTH_JOB}" | grep -v '^$' | crontab -

echo "[setup_cron] installed:"
crontab -l | grep -E "ZONEAPP_MARKET_CLOSE|ZONEAPP_HEALTH_CHECK"
echo "[setup_cron] market-close log: ${CRON_LOG}"
echo "[setup_cron] health-check log: ${HEALTH_LOG}"
