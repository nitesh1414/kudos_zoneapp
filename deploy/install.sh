#!/usr/bin/env bash
# Install the Python service on Ubuntu. Provision TimescaleDB separately (or
# use docker-compose.yml) and create /opt/zoneapp/.env first.
set -euo pipefail
APP_DIR=/opt/zoneapp
if [ ! -f "$APP_DIR/.env" ]; then
  echo "Missing $APP_DIR/.env. Copy backend/.env.example, set DATABASE_URL and all secrets, then rerun."
  exit 1
fi
apt-get update
apt-get install -y python3-venv python3-pip nginx curl
id -u zoneapp &>/dev/null || useradd -r -s /usr/sbin/nologin -d "$APP_DIR" zoneapp
mkdir -p "$APP_DIR/data/uploads"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
chmod 600 "$APP_DIR/.env"
chown -R zoneapp:zoneapp "$APP_DIR/data"
cp "$APP_DIR/deploy/zoneapp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now zoneapp
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/zoneapp
ln -sf "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-enabled/zoneapp
nginx -t && systemctl reload nginx
# Merge the sample schedule manually if this account already has other jobs.
crontab -u zoneapp "$APP_DIR/deploy/crontab.example"
echo "ZoneApp installed. Sign in with ZONEAPP_ADMIN_USERNAME at your configured host."
