#!/usr/bin/env bash
set -e

# Resolve project root directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python"

# Fallback to system python3 if no local venv is found
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="$(which python3)"
fi

CRON_LOG="${PROJECT_DIR}/logs/cron.log"
mkdir -p "${PROJECT_DIR}/logs"

# 1. Define the cron schedule (Every Mon-Fri at 08:30 AM IST)
CRON_TAG="# ZONE_LEVELS_TOKEN_JOB"
CRON_CMD="30 8 * * 1-5 cd ${PROJECT_DIR} && ${VENV_PYTHON} ${PROJECT_DIR}/generate_token.py >> ${CRON_LOG} 2>&1"

# 2. Read existing crontab, remove any old version of this job, and add the new one
CURRENT_CRON=$(crontab -l 2>/dev/null | grep -v "${CRON_TAG}" || true)

echo "${CURRENT_CRON}
${CRON_CMD} ${CRON_TAG}" | crontab -

echo "[DEPLOY] Automated Cron job registered successfully:"
crontab -l | grep "${CRON_TAG}"