# Deploying ZoneApp on the VPS (nginx + PM2 + PostgreSQL)

Target environment: a VPS that **already runs other applications on ports
8000–8003 and 5173**, with **Node, Python, PM2, PostgreSQL and nginx already
installed**. This guide adds ZoneApp without touching the existing apps.

Everything below is executed once, in order, as a sudo-capable user.
Commands that need root are prefixed with `sudo`.

---

## 0. Architecture and port plan

```
browser ──► nginx :80 / :443 (public)
                └──► proxy_pass ──► uvicorn 127.0.0.1:8004  (PM2: "zoneapp")
                                          └──► PostgreSQL 127.0.0.1:5432 (existing)
```

Key facts about this application:

- **One process serves everything.** The React frontend is compiled into
  `backend/app/static/` (`cd frontend && npm run build`) and FastAPI serves it.
  **Port 5173 (the Vite dev server) is never used in production** — the busy
  5173 on this VPS belongs to something else and is irrelevant here.
- **uvicorn binds to 127.0.0.1 only.** nginx is the only public listener; the
  app port is never opened in the firewall.

| Port  | Used by                        | Status on this VPS      |
|-------|--------------------------------|-------------------------|
| 8000–8003 | existing applications       | occupied — do not touch |
| 5173  | existing application (Vite?)   | occupied — do not touch |
| **8004** | ZoneApp API + SPA (uvicorn) | **new, localhost only** |
| 80/443 | nginx (shared)                 | existing, we add a vhost |

If 8004 is somehow taken as well, pick the next free one — then use the same
number in three places: `ecosystem.config.js` (`ZONEAPP_PORT=…`), the nginx
`proxy_pass` line, and the cron entries.

```bash
# Confirm what is listening before you start:
sudo ss -ltnp | grep -E ':(800[0-9]|5173)\s'
```

Install directory used throughout: **`/opt/zoneapp`**.

---

## 1. Prerequisites (already installed — verify versions)

```bash
node -v      # >= 18   (Vite 6 requirement)
python3 -V   # >= 3.10 (code uses `X | Y` type unions)
pm2 -v
psql --version
nginx -v
```

Only small packages may be missing; install them if the checks fail:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip git curl
```

---

## 2. Get the code onto the server

```bash
sudo mkdir -p /opt/zoneapp

# Option A — clone (recommended):
sudo git clone https://github.com/nitesh1414/kudos_zoneapp.git /opt/zoneapp
sudo chown -R $USER:$USER /opt/zoneapp

# Option B — from your machine:
#   rsync -avz --exclude node_modules --exclude 'backend/venv' ./ user@VPS:/opt/zoneapp
```

> The compiled frontend bundle (`backend/app/static/`) is committed to this
> repository, so a fresh clone is deployable as-is. Section 5 rebuilds it
> whenever frontend code changes.

---

## 3. Create the database (existing PostgreSQL)

ZoneApp needs one database and one login role. As the postgres superuser:

```bash
sudo -u postgres psql
```

```sql
CREATE ROLE zoneapp LOGIN PASSWORD 'pick-a-strong-db-password';
CREATE DATABASE zoneapp OWNER zoneapp;
\q
```

Verify connectivity from the app's point of view:

```bash
psql "postgresql://zoneapp:pick-a-strong-db-password@127.0.0.1:5432/zoneapp" -c 'select 1;'
```

Notes:

- All tables are created automatically on first start — no SQL to run by hand.
- TimescaleDB is **optional**: if the extension is installed and available,
  ZoneApp turns the candle table into a hypertable; plain PostgreSQL works fine.

---

## 4. Python environment and configuration

```bash
cd /opt/zoneapp
python3 -m venv backend/venv
backend/venv/bin/pip install --upgrade pip
backend/venv/bin/pip install -r backend/requirements.txt
```

Create the one config file every process reads:

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

Generate the two secrets you need before editing:

```bash
openssl rand -hex 32     # -> ZONEAPP_API_KEY
backend/venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # -> ZONEAPP_ENCRYPTION_KEY
```

Edit `backend/.env`:

```ini
DATABASE_URL=postgresql://zoneapp:pick-a-strong-db-password@127.0.0.1:5432/zoneapp

ZONEAPP_ADMIN_USERNAME=admin
ZONEAPP_ADMIN_PASSWORD=<strong password — first sign-in>

ZONEAPP_API_KEY=<openssl rand -hex 32 output>
ZONEAPP_ENCRYPTION_KEY=<fernet key — never change it later, it encrypts broker tokens>

# Plain HTTP for now -> false. Switch to true the moment HTTPS (§8) works,
# otherwise browsers will not send the login cookie.
ZONEAPP_SECURE_COOKIES=false

ZONEAPP_SYMBOL=NSE:NIFTY50-INDEX
FYERS_CLIENT_ID=your-fyers-client-id
FYERS_SECRET_KEY=your-fyers-secret-key
FYERS_REDIRECT_URI=https://fyers.in/
```

---

## 5. Build the frontend (Node)

Only needed when frontend code changed — the repo ships a compiled bundle.
Run it from the repo root each deploy to be safe:

```bash
cd /opt/zoneapp/frontend
npm ci
npm run build        # writes ../backend/app/static/  (served by FastAPI)
```

No dev server is started; nothing listens on 5173.

---

## 6. Run the API under PM2

The repo ships `ecosystem.config.js` (port 8004, uvicorn via the venv, one
worker — bootstrapping/seeding run in-process, matching the reference systemd
unit in `deploy/zoneapp.service`).

```bash
cd /opt/zoneapp
pm2 start ecosystem.config.js
pm2 save                       # remember the process list

# Survive reboots (skip if `pm2 startup` was configured on this VPS already):
pm2 startup                    # run the command it prints, with sudo
```

Check it:

```bash
pm2 status                # zoneapp should be "online"
pm2 logs zoneapp --lines 50
curl -i http://127.0.0.1:8004/     # expect: 307 redirect to /login
```

The first start creates the schema and the administrator account from
`ZONEAPP_ADMIN_*`. If startup fails, `pm2 logs zoneapp` shows the exact
missing setting (most commonly `DATABASE_URL` or the admin password).

---

## 7. nginx vhost

The repo ships `deploy/nginx-vps.conf` for this setup. Edit one line first:

```bash
nano /opt/zoneapp/deploy/nginx-vps.conf     # set server_name to your domain or the VPS IP
```

Enable it:

```bash
sudo cp /opt/zoneapp/deploy/nginx-vps.conf /etc/nginx/sites-available/zoneapp
sudo ln -sf /etc/nginx/sites-available/zoneapp /etc/nginx/sites-enabled/zoneapp
sudo nginx -t && sudo systemctl reload nginx
```

This coexists with your other vhosts: nginx routes by `server_name`, and only
this vhost proxies to 8004. The vhost sets the usual `X-Forwarded-*` headers,
`proxy_read_timeout 300s` (history backfills can run long) and
`client_max_body_size 25M` (CSV uploads used by the app).

If nginx on this VPS uses `conf.d` instead of `sites-available/enabled`, copy
the file to `/etc/nginx/conf.d/zoneapp.conf` instead — no symlink needed.

**Firewall** — keep 8004 private:

```bash
sudo ufw status
# 80/443 open, 8004 NOT open. Also check the cloud provider's security group.
```

---

## 8. HTTPS (recommended, do right after the smoke test)

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d zoneapp.example.com
```

Then flip cookies to secure and restart:

```bash
sed -i 's/^ZONEAPP_SECURE_COOKIES=.*/ZONEAPP_SECURE_COOKIES=true/' /opt/zoneapp/backend/.env
pm2 restart zoneapp
```

---

## 9. Smoke test

1. `https://zoneapp.example.com/` → redirects to the login screen.
2. Sign in with `ZONEAPP_ADMIN_USERNAME` / `ZONEAPP_ADMIN_PASSWORD`.
3. Admin panel → **Broker connections**: add the Fyers connection + today's
   token; historical seeding starts automatically after saving.
4. **Market symbols** / **Market-close job** tabs should show data appearing.
5. Client tabs visible: Overview, Next-session zones, Base rates, Gap & CPR
   (the **Sessions** tab is hidden from clients and listed for admins only —
   see the `adminOnly` flag in `frontend/src/components/Layout.jsx` and the
   route wrapper in `frontend/src/App.jsx`).

Unauthenticated checks from the server:

```bash
curl -I http://127.0.0.1:8004/          # 307 -> /login
curl -s http://127.0.0.1:8004/login | head    # HTML of the SPA
```

---

## 10. Scheduled jobs (cron)

The market-close calculation is triggered by HTTP, not by an internal
scheduler. Install the two entries from `deploy/crontab.example`, adapted to
this deployment (venv at `backend/venv`, API on **8004**):

```bash
crontab -e
```

```cron
# EOD zone calculation, 17:00 India time, trading weekdays. Idempotent + weekend/holiday-aware.
CRON_TZ=Asia/Kolkata
0 17 * * 1-5 . /opt/zoneapp/backend/.env; curl --retry 3 --retry-delay 60 --fail-with-body -X POST http://127.0.0.1:8004/api/jobs/market-close -H "X-API-Key: ${ZONEAPP_API_KEY}" >> /opt/zoneapp/logs/market-close.log 2>&1
# Data sanity guard 20 minutes later:
20 17 * * 1-5 cd /opt/zoneapp && backend/venv/bin/python scripts/health_check.py >> /opt/zoneapp/logs/health-check.log 2>&1
```

```bash
mkdir -p /opt/zoneapp/logs
```

---

## 11. Day-2 operations

**Deploy an update**

```bash
cd /opt/zoneapp
git pull
backend/venv/bin/pip install -r backend/requirements.txt   # only if deps changed
cd frontend && npm ci && npm run build && cd ..             # only if frontend changed
pm2 restart zoneapp
```

**Useful commands**

```bash
pm2 logs zoneapp --lines 100     # tail application logs
pm2 monit                        # live CPU/RPM dashboard
pm2 restart zoneapp              # graceful reload
pm2 delete zoneapp               # remove from PM2 (then `pm2 save`)
```

**Database backup** (everything derived — zones, outcomes — can be rebuilt
from candles, but back them up anyway):

```cron
30 2 * * * sudo -u postgres pg_dump -Fc zoneapp > /opt/zoneapp/logs/zoneapp-$(date +\%F).dump 2>>/opt/zoneapp/logs/backup.log
```

Keep the dumps off the VPS (rsync/object storage) for real protection.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `pm2 status` shows *errored* repeatedly | `pm2 logs zoneapp` — usually a bad `DATABASE_URL` or missing `ZONEAPP_ADMIN_PASSWORD` on very first boot |
| 502 from nginx | uvicorn not running (`pm2 status`) or listening on a different port than the vhost's `proxy_pass` |
| Login loops back to the login page | `ZONEAPP_SECURE_COOKIES=true` while still on plain HTTP — set `false` until HTTPS works |
| `503 Frontend build is missing` | `backend/app/static/` absent — run §5, then `pm2 restart zoneapp` |
| Tables never created / permission denied | DB role lacks rights on the `zoneapp` database — recheck §3 |
| Market-close cron silently does nothing | Check `/opt/zoneapp/logs/market-close.log`; `ZONEAPP_API_KEY` in crontab must equal the one in `backend/.env` |
| Port conflict on 8004 | `sudo ss -ltnp | grep 8004`, choose another port, update ecosystem + nginx + cron |

---

## Quick reference — what lives where

| Path | Purpose |
|---|---|
| `/opt/zoneapp` | application code (git checkout) |
| `/opt/zoneapp/backend/.env` | all configuration and secrets (chmod 600) |
| `/opt/zoneapp/backend/venv` | Python virtualenv |
| `/opt/zoneapp/backend/app/static` | compiled React app (served by FastAPI) |
| `/opt/zoneapp/logs` | cron logs (market-close, health check) |
| `/etc/nginx/sites-available/zoneapp` | nginx vhost → 127.0.0.1:8004 |
| PM2 process `zoneapp` | uvicorn, started via `ecosystem.config.js` |
