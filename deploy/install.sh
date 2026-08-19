#!/usr/bin/env bash
# Ubuntu 22.04/24.04 VPS. Run as root.
set -euo pipefail

APP_DIR=/opt/zoneapp
apt-get update
apt-get install -y python3-venv python3-pip nginx apache2-utils curl

id -u zoneapp &>/dev/null || useradd -r -s /bin/false -d "$APP_DIR" zoneapp
mkdir -p "$APP_DIR"/{data,data/uploads,backups}

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/backend/.env.example" "$APP_DIR/.env"
  KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
  sed -i "s|^ZONEAPP_API_KEY=.*|ZONEAPP_API_KEY=$KEY|" "$APP_DIR/.env"
  echo "Generated API key: $KEY"
fi
chmod 600 "$APP_DIR/.env"
chown -R zoneapp:zoneapp "$APP_DIR"

cp "$APP_DIR/deploy/zoneapp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now zoneapp

cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/zoneapp
ln -sf /etc/nginx/sites-available/zoneapp /etc/nginx/sites-enabled/zoneapp
echo "Set a dashboard password:"
htpasswd -c /etc/nginx/.htpasswd admin
nginx -t && systemctl reload nginx

echo
echo "Done. Next:"
echo "  1. Edit server_name in /etc/nginx/sites-available/zoneapp, then: certbot --nginx"
echo "  2. Seed history:  sudo -u zoneapp $APP_DIR/venv/bin/python $APP_DIR/scripts/seed.py /path/to/bars.csv"
echo "  3. Add a broker adapter when one is chosen (see backend/app/brokers/README.md)."
