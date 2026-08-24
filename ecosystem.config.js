// PM2 process definition for the ZoneApp API.
// Used by docs/DEPLOYMENT_VPS.md — pm2 start ecosystem.config.js
// Ports 8000-8003 and 5173 are already taken by other apps on the target VPS,
// so the API listens on 8004 by default. Override with ZONEAPP_PORT.
const port = process.env.ZONEAPP_PORT || 8004

module.exports = {
  apps: [
    {
      name: 'zoneapp',
      cwd: __dirname + '/backend',
      script: './venv/bin/uvicorn',   // the venv binary, run directly
      interpreter: 'none',            // it is not a Node script
      args: `app.main:app --host 127.0.0.1 --port ${port} --workers 1`,
      // One worker on purpose: bootstrapping, seeding and background tasks
      // run inside the API process (the repo's systemd unit does the same).
      max_memory_restart: '512M',
      env: { PYTHONUNBUFFERED: '1' },
    },
  ],
}
