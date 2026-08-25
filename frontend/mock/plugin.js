/**
 * Development-only mock API.
 *
 * Enabled with ZONEAPP_MOCK=1 (npm run dev:mock) so the interface can be
 * previewed without PostgreSQL. It is never part of a production build.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const db = JSON.parse(readFileSync(join(here, 'data.json'), 'utf8'))

const json = (res, body, status = 200) => {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(body))
}

const readBody = (req) =>
  new Promise((resolve) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {})
      } catch {
        resolve({})
      }
    })
  })

// ---- deterministic fake candles for the session chart ----------------------
const round2 = (v) => Math.round(v * 100) / 100
const fnv1a = (s) => {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) }
  return h >>> 0
}
const prng = (a) => () => {
  a |= 0; a = (a + 0x6d2b79f5) | 0
  let t = Math.imul(a ^ (a >>> 15), 1 | a)
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}
const FIRST_STORED = '2024-03-04'
const LAST_STORED = '2026-08-20'

const businessDays = (from, to, max = 62) => {
  const out = []
  const d = new Date(`${from}T00:00:00Z`)
  const end = new Date(`${to}T00:00:00Z`)
  while (d <= end && out.length < max) {
    const w = d.getUTCDay()
    if (w !== 0 && w !== 6) out.push(d.toISOString().slice(0, 10))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

/** NSE session: 09:15 → 15:15 candle starts, like the real feed. */
const mockCandles = (days, resolution, seedBase) => {
  const step = resolution === 'D' ? null : Math.max(1, Number(resolution) || 15)
  const rand = prng(fnv1a(`candles:${seedBase}:${resolution}`))
  let px = 24760
  const bars = []
  for (const day of days) {
    const times = []
    if (step) for (let t = 9 * 60 + 15; t <= 15 * 60 + 15; t += step) times.push(t)
    else times.push(9 * 60 + 15)
    for (const t of times) {
      const o = px
      px = round2(px + (rand() - 0.5) * (step ? 18 : 140))
      const hh = String(Math.floor(t / 60)).padStart(2, '0')
      const mm = String(t % 60).padStart(2, '0')
      bars.push({
        ts: `${day}T${hh}:${mm}:00`,
        o: round2(o),
        h: round2(Math.max(o, px) + rand() * (step ? 9 : 60)),
        l: round2(Math.min(o, px) - rand() * (step ? 9 : 60)),
        c: round2(px),
        v: Math.floor(400_000 + rand() * 1_900_000),
      })
    }
  }
  return bars
}

/** Chart backend: mirrors session_chart() in the real service. */
const mockSessionChart = (res, q, symbol, admin) => {
  const resolution = q.get('resolution') || '15'
  const date = q.get('date')
  const from = q.get('date_from')
  const to = q.get('date_to')
  let start, end
  const snapDown = (day) => {
    const d = new Date(`${day}T00:00:00Z`)
    while ([0, 6].includes(d.getUTCDay())) d.setUTCDate(d.getUTCDate() - 1)
    return d.toISOString().slice(0, 10)
  }
  if (date) {
    if (date < FIRST_STORED) return json(res, { detail: `No candles stored on or before ${date}` }, 404)
    start = end = snapDown(date > LAST_STORED ? LAST_STORED : date)
  } else {
    if (from && from > LAST_STORED)
      return json(res, { detail: `Range starts after the last stored session (${LAST_STORED})` }, 404)
    end = snapDown(!to || to > LAST_STORED ? LAST_STORED : to)
    start = !from ? end : from < FIRST_STORED ? FIRST_STORED : snapDown(from)
    if (start > end) return json(res, { detail: `No candles stored between ${from} and ${to}` }, 404)
  }
  const days = businessDays(start, end)
  if (!days.length) return json(res, { detail: 'No candles stored for this window' }, 404)
  end = days[days.length - 1]
  start = days[0]

  const side = (label) => (label.startsWith('R') ? 'R' : label.startsWith('S') ? 'S' : 'AT')
  const rows = db.dashboard.zones.rows.map((z) => ({ ...z, side: side(z.label) }))
  const rand = prng(fnv1a(`results:${end}`))
  const level = (z) =>
    Object.assign(
      { label: z.label, lo: z.lo, hi: z.hi, key: z.key, key_name: z.key_name, side: z.side },
      admin ? { stars: z.stars } : {},
    )
  const resultsFor = ['HELD', 'TOUCHED', 'BROKE', 'NOT REACHED', 'TOUCHED', 'NOT REACHED']
  return json(res, {
    symbol,
    resolution,
    mode: start === end ? 'day' : 'range',
    date: end,
    date_from: start,
    date_to: end,
    first_date: FIRST_STORED,
    last_date: LAST_STORED,
    basis: db.dashboard.zones.basis,
    day_type: db.dashboard.zones.day_type,
    levels: rows.map((z) => ({ ...level(z), result: resultsFor[Math.floor(rand() * resultsFor.length)] })),
    next_levels: end === LAST_STORED ? rows.map(level) : [],
    candles: mockCandles(days, resolution, end),
    truncated: false,
  })
}

export default function mockApi() {
  if (!process.env.ZONEAPP_MOCK) return { name: 'zoneapp-mock-api-disabled' }
  let loggedIn = false
  let nextId = 90

  return {
    name: 'zoneapp-mock-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url, 'http://mock')
        const path = url.pathname
        if (!path.startsWith('/api/')) return next()
        const body = req.method === 'GET' ? {} : await readBody(req)

        if (path === '/api/auth/login') {
          if (!body.username || !body.password) return json(res, { detail: 'Invalid username or password' }, 401)
          db.me.role = String(body.username).toLowerCase().includes('admin') ? 'admin' : 'client'
          db.me.username = body.username
          db.me.display_name = db.me.role === 'admin' ? 'Administrator' : 'Demo Client'
          loggedIn = true
          return json(res, { ok: true, role: db.me.role, redirect: '/' })
        }
        if (path === '/api/auth/logout') {
          loggedIn = false
          return json(res, { ok: true })
        }
        if (!loggedIn) return json(res, { detail: 'Please log in' }, 401)

        const admin = db.me.role === 'admin'
        // Star ratings are administrator-only, exactly like the API does it.
        const stripStars = (payload) => {
          const clone = JSON.parse(JSON.stringify(payload))
          for (const row of clone.zones?.rows || []) { delete row.stars; delete row.weight }
          for (const row of clone.session_recap?.zones || []) { delete row.stars; delete row.weight }
          return clone
        }

        if (path === '/api/me') return json(res, db.me)
        if (path === '/api/dashboard') {
          const payload = admin ? db.dashboard : stripStars(db.dashboard)
          return json(res, { ...payload, role: db.me.role, username: db.me.username, authenticated: true, can_edit: admin })
        }
        if (path === '/api/health') return json(res, db.health)
        if (path === '/api/stats/zones') {
          const { by_stars, ...rest } = db.stats_zones
          return json(res, admin ? db.stats_zones : rest)
        }
        if (path === '/api/stats/days') return json(res, db.stats_days)
        if (path === '/api/sessions') return json(res, db.sessions)
        if (path === '/api/chart/session')
          return mockSessionChart(res, url.searchParams, url.searchParams.get('symbol') || db.dashboard.symbol, admin)
        if (path === '/api/data-status')
          return json(res, { connected: true, status: 'valid', broker: 'Main Fyers account',
                             message: 'Market data is live until 21 Aug, 06:30 PM IST.' })
        const loginUrl = path.match(/^\/api\/admin\/brokers\/(\d+)\/login-url$/)
        if (loginUrl)
          return json(res, { ok: true, url: 'https://api-t1.fyers.in/api/v3/generate-authcode?client_id=DEMO-100&state=mock' })
        const exchange = path.match(/^\/api\/admin\/brokers\/(\d+)\/exchange-token$/)
        if (exchange) {
          if (!body.auth_code) return json(res, { detail: 'No auth_code found.' }, 400)
          return json(res, { ok: true, access_token: 'mock.' + 'a'.repeat(120) })
        }
        if (path === '/api/instruments') return json(res, { items: db.instruments, segments: ['NSE cash & indices'] })
        if (path === '/api/admin/broker-types') return json(res, db.broker_types)
        if (path === '/api/admin/brokers') return json(res, db.brokers)
        if (path === '/api/admin/holidays') return json(res, db.holidays)
        if (path === '/api/admin/job-runs') return json(res, db.job_runs)
        if (path === '/api/symbols') return json(res, admin ? db.symbols : db.symbols.filter((s) => s.active))
        if (path === '/api/admin/symbols' && req.method === 'POST') {
          const alias = { NIFTY: 'NSE:NIFTY50-INDEX', BANKNIFTY: 'NSE:NIFTYBANK-INDEX', FINNIFTY: 'NSE:FINNIFTY-INDEX',
            MIDCPNIFTY: 'NSE:MIDCPNIFTY-INDEX', SENSEX: 'BSE:SENSEX-INDEX' }
          const clean = alias[String(body.symbol || '').trim().toUpperCase()] || String(body.symbol || '').trim().toUpperCase()
          if (!db.symbols.some((s) => s.symbol === clean))
            db.symbols.push({ symbol: clean, label: body.label || '', resolutions: body.resolutions || ['15', 'D'],
              broker_id: body.broker_id || null, broker_name: db.brokers.find((b) => b.id === body.broker_id)?.name || null,
              active: true, created_at: new Date().toISOString(), bars: 0, sessions: 0, last_bar_date: null, clients: 0 })
          return json(res, { ok: true, symbol: clean, seeding: true,
            seed_message: `Backfilling ${body.seed_days || 180} days for ${clean} in the background.` })
        }
        const symbolMatch = path.match(/^\/api\/admin\/symbols\/(.+?)(\/seed)?$/)
        if (symbolMatch) {
          const name = decodeURIComponent(symbolMatch[1])
          const row = db.symbols.find((s) => s.symbol === name)
          if (symbolMatch[2]) return json(res, { ok: true, seeding: true, seed_symbols: [name],
            seed_message: `Backfilling ${body.days || 180} days for ${name} in the background.` })
          if (req.method === 'PATCH' && row) { Object.assign(row, body); return json(res, { ok: true }) }
          if (req.method === 'DELETE') { db.symbols = db.symbols.filter((s) => s.symbol !== name); return json(res, { ok: true, symbol: name }) }
        }
        if (path === '/api/admin/seed') {
          const names = body.symbols?.length ? body.symbols : db.symbols.filter((s) => s.active).map((s) => s.symbol)
          const today = new Date().toISOString().slice(0, 10)
          const from = body.date_from || new Date(Date.now() - (body.days || 180) * 864e5).toISOString().slice(0, 10)
          const to = body.date_to || today
          names.forEach((symbol, i) =>
            db.job_runs.unshift({
              id: Date.now() + i, job_date: today, broker_id: 1, broker_name: 'Main Fyers account', symbol,
              kind: 'seed', status: i === 0 ? 'running' : 'success',
              detail: { date_from: from, date_to: to, bars_ingested: 4820, sessions_scored: 61 },
              started_at: new Date().toISOString(), finished_at: i === 0 ? null : new Date().toISOString(),
            }),
          )
          return json(res, { ok: true, seeding: true, seed_symbols: names, date_from: from, date_to: to,
            seed_message: `Fetching ${from} to ${to} for ${names.length} symbol(s) in the background.` })
        }
        if (path === '/api/admin/seed-all') {
          const names = db.symbols.filter((s) => s.active).map((s) => s.symbol)
          return json(res, { ok: true, seeding: true, seed_symbols: names,
            seed_message: `Backfilling ${body.days || 180} days for ${names.length} symbol(s) in the background.` })
        }
        if (path === '/api/admin/gift-nifty') return json(res, db.dashboard.gift_nifty)

        if (path === '/api/admin/clients') {
          if (req.method === 'GET') return json(res, db.clients)
          if (req.method === 'POST') {
            const row = {
              id: nextId++, username: body.username, display_name: body.display_name,
              active: true, created_at: new Date().toISOString(),
            }
            db.clients.unshift(row)
            return json(res, { ok: true, id: row.id })
          }
        }
        const clientMatch = path.match(/^\/api\/admin\/clients\/(\d+)$/)
        if (clientMatch) {
          const id = Number(clientMatch[1])
          const row = db.clients.find((c) => c.id === id)
          if (!row) return json(res, { detail: 'Client not found' }, 404)
          if (req.method === 'PATCH') {
            for (const k of ['display_name', 'symbol', 'active']) if (body[k] !== undefined && body[k] !== null) row[k] = body[k]
            if ('broker_id' in body) {
              row.broker_id = body.broker_id
              row.broker_name = db.brokers.find((b) => b.id === body.broker_id)?.name || null
            }
            return json(res, { ok: true })
          }
          if (req.method === 'DELETE') {
            db.clients = db.clients.filter((c) => c.id !== id)
            return json(res, { ok: true })
          }
        }
        if (path.endsWith('/test')) return json(res, { connected: true, message: 'Mock broker reachable' })
        const tokenMatch = path.match(/^\/api\/brokers\/(\d+)\/token$/)
        const seedMatch = path.match(/^\/api\/admin\/brokers\/(\d+)\/seed$/)
        if (tokenMatch || seedMatch) {
          const symbols = ['NSE:NIFTY50-INDEX']
          const days = body.seed_days || body.days || 180
          db.job_runs.unshift({
            id: Date.now(), job_date: new Date().toISOString().slice(0, 10), broker_id: 1,
            broker_name: 'Main Fyers account', symbol: symbols[0], kind: 'seed', status: 'success',
            detail: { bars_ingested: 6120, by_resolution: { 15: 5880, D: 240 }, days, sessions_scored: 118 },
            started_at: new Date().toISOString(), finished_at: new Date().toISOString(),
          })
          return json(res, {
            ok: true, connected: true, message: 'Token verified with the provider.',
            seeding: true, seed_symbols: symbols,
            seed_message: `Backfilling ${days} days for ${symbols.join(', ')} in the background.`,
          })
        }
        if (path.includes('/jobs/market-close')) return json(res, { ok: true, status: 'completed', message: 'Mock run finished', sessions_scored: 3 })
        return json(res, { ok: true, mock: true })
      })
    },
  }
}
