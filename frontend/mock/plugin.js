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
const istToday = () => new Date(Date.now() + (330 + new Date().getTimezoneOffset()) * 60000).toISOString().slice(0, 10)
const istNow = () => new Date(Date.now() + (330 + new Date().getTimezoneOffset()) * 60000)
const addDays = (day, n) => {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
const isWeekend = (day) => [0, 6].includes(new Date(`${day}T00:00:00Z`).getUTCDay())
const snapDown = (day) => { let d = day; while (isWeekend(d)) d = addDays(d, -1); return d }
const snapUp = (day) => { let d = day; while (isWeekend(d)) d = addDays(d, 1); return d }
const nextBizDay = (day) => snapUp(addDays(day, 1))
// A weekday session is complete only after the close. Reading the hour here is
// what makes the preview behave like the real backend during market hours:
// today is stored (possibly partially) but the last COMPLETE day is yesterday.
const TODAY = istToday()
const TODAY_COMPLETE = !isWeekend(TODAY) && Number(istNow().toISOString().slice(11, 13)) >= 16
const LAST_STORED = snapDown(TODAY)
const LAST_COMPLETE = TODAY_COMPLETE ? snapDown(TODAY) : snapDown(addDays(TODAY, -1))
const NEXT_SESSION_DATE = (TODAY_COMPLETE || isWeekend(TODAY)) ? nextBizDay(LAST_COMPLETE) : TODAY

const businessDays = (from, to, max = 62) => {
  const out = []
  let d = snapUp(from)
  while (d <= to && out.length < max) {
    if (!isWeekend(d)) out.push(d)
    d = addDays(d, 1)
  }
  return out
}

/** One session's 15-minute candles, seeded per day so every window shows the
 * same bars. Closes chain across sessions (a day opens near the previous
 * business day's close) and ranges stay Nifty-sized, so zones spread into
 * proper R1–R4 / S1–S4 ladders. NSE session: 09:15 → 15:15 candle starts. */
const barsCache = new Map()
const dayBars = (day, resolution = '15') => {
  if (resolution === 'D') {
    const b = dayBars(day, '15')
    return [{
      ts: b[0].ts, o: b[0].o,
      h: round2(Math.max(...b.map((x) => x.h))),
      l: round2(Math.min(...b.map((x) => x.l))),
      c: b[b.length - 1].c,
      v: b.reduce((a, x) => a + x.v, 0),
    }]
  }
  const key = `${day}:15`
  if (barsCache.has(key)) return barsCache.get(key).map((b) => ({ ...b }))
  const rand = prng(fnv1a(`candles:${day}`))
  const anchor = day <= FIRST_STORED
    ? 23800 + (fnv1a(`anchor:${day}`) % 1200)
    : dayOHLC(snapDown(addDays(day, -1))).c
  let px = anchor + round2((rand() - 0.5) * 24) // small overnight gap
  const bars = []
  for (let t = 9 * 60 + 15; t <= 15 * 60 + 15; t += 15) {
    const o = px
    px = round2(px + (rand() - 0.5) * 30)
    const hh = String(Math.floor(t / 60)).padStart(2, '0')
    const mm = String(t % 60).padStart(2, '0')
    bars.push({
      ts: `${day}T${hh}:${mm}:00`,
      o: round2(o),
      h: round2(Math.max(o, px) + rand() * 13),
      l: round2(Math.min(o, px) - rand() * 13),
      c: round2(px),
      v: Math.floor(400_000 + rand() * 1_900_000),
    })
  }
  barsCache.set(key, bars)
  return bars.map((b) => ({ ...b }))
}

const dayOHLC = (day) => {
  const bars = dayBars(day)
  return {
    o: bars[0].o,
    h: Math.max(...bars.map((b) => b.h)),
    l: Math.min(...bars.map((b) => b.l)),
    c: bars[bars.length - 1].c,
  }
}

/** Pivot-family zones for the session AFTER `basisDay`, mirroring zones.py
 * (weights and the anchor clustering) in miniature. */
const W8 = {
  PP: 1, TC: 0.5, BC: 0.5, PDC: 1, PDH: 0.6, PDL: 0.8,
  CamR3: 0.6, CamR4: 0.4, CamS3: 1, CamS4: 0.7,
  FibR1: 0.7, FibR2: 0.4, FibS1: 0.8, FibS2: 0.8, ClaR1: 0.4, ClaS1: 0.8,
}
const mockZones = (basisDay) => {
  const { h: H, l: L, c: C } = dayOHLC(basisDay)
  const r = H - L
  const pp = (H + L + C) / 3
  const bc = (H + L) / 2
  const tc = 2 * pp - bc
  const cand = {
    PP: pp, TC: tc, BC: bc, PDC: C, PDH: H, PDL: L,
    CamR3: C + (r * 1.1) / 4, CamR4: C + (r * 1.1) / 2,
    CamS3: C - (r * 1.1) / 4, CamS4: C - (r * 1.1) / 2,
    FibR1: pp + 0.382 * r, FibR2: pp + 0.618 * r,
    FibS1: pp - 0.382 * r, FibS2: pp - 0.618 * r,
    ClaR1: 2 * pp - L, ClaS1: 2 * pp - H,
  }
  const items = Object.entries(cand).sort((a, b) => a[1] - b[1])
  const zones = []
  let i = 0
  while (i < items.length) {
    const [an, av] = items[i]
    let hi = av
    let best = av; let bestN = an; let bestW = W8[an] ?? 0.3
    const members = [an]
    let j = i + 1
    while (j < items.length && items[j][1] - av <= 25) {
      const [nm, v] = items[j]
      hi = v
      members.push(nm)
      if ((W8[nm] ?? 0.3) > bestW) { bestW = W8[nm]; best = v; bestN = nm }
      j++
    }
    const mid = (av + hi) / 2
    zones.push({
      lo: round2(Math.min(av, mid - 12)),
      hi: round2(Math.max(hi, mid + 12)),
      key: round2(best),
      key_name: bestN,
      members: members.join('+'),
    })
    i = j
  }
  const at = zones.find((z) => z.lo <= C && C <= z.hi) || null
  const rest = zones.filter((z) => z !== at)
  const res4 = rest.filter((z) => (z.lo + z.hi) / 2 > C).slice(0, 4)
  const sup4 = rest.filter((z) => (z.lo + z.hi) / 2 < C).reverse().slice(0, 4)
  const out = []
  res4.forEach((z, k) => out.push({ ...z, label: `R${k + 1}`, side: 'R' }))
  sup4.forEach((z, k) => out.push({ ...z, label: `S${k + 1}`, side: 'S' }))
  if (at) out.push({ ...at, label: 'AT', side: 'AT' })
  const cprPct = (100 * Math.abs(tc - bc)) / C
  return {
    zones: out.sort((a, b) => b.key - a.key),
    dayType: cprPct < 0.08 ? 'NARROW' : cprPct > 0.26 ? 'WIDE' : 'NORMAL',
  }
}

const asLevel = (z, admin) =>
  Object.assign(
    { label: z.label, lo: z.lo, hi: z.hi, key: z.key, key_name: z.key_name, side: z.side },
    admin ? { stars: Math.min(5, 1 + (fnv1a(z.members) % 5)) } : {},
  )

/** One session's zones, built from the session before it — the shape the real
 * backend returns in day_levels, so the chart's per-session level drawing can be
 * previewed without PostgreSQL. A session still running has no results yet. */
const daySheet = (day, admin) => {
  const basisDay = snapDown(addDays(day, -1))
  const sheet = mockZones(basisDay)
  const { h: high, l: low, c: close } = dayOHLC(basisDay)
  const rand = prng(fnv1a(`results:${day}`))
  const RESULTS = ['HELD', 'TOUCHED', 'BROKE', 'NOT REACHED', 'TOUCHED', 'NOT REACHED']
  const scored = day !== TODAY || TODAY_COMPLETE
  return {
    date: day,
    basis: { date: basisDay, high, low, close },
    day_type: sheet.dayType,
    levels: sheet.zones.map((z) => ({
      ...asLevel(z, admin),
      result: scored ? RESULTS[Math.floor(rand() * RESULTS.length)] : null,
    })),
  }
}

// Mirrors MAX_DAY_LEVELS in backend/app/service.py.
const MAX_DAY_LEVELS = 20

/** Chart backend: mirrors session_chart() in the real service. The viewed
 * session's levels come from the previous business day's OHLC; the next
 * session's levels come from the viewed day's OHLC — two distinct line sets. */
const mockSessionChart = (res, q, symbol, admin) => {
  const resolution = q.get('resolution') || '15'
  const date = q.get('date')
  const from = q.get('date_from')
  const to = q.get('date_to')
  const view = (q.get('view') || 'latest').toLowerCase()
  const completedDays = businessDays(FIRST_STORED, LAST_COMPLETE, 5000)
  if (!completedDays.length)
    return json(res, { detail: 'No completed session available yet; the market has not closed today' }, 404)
  let levelEnd, candleStart, candleEnd
  if (date) {
    if (date < FIRST_STORED) return json(res, { detail: `No candles stored on or before ${date}` }, 404)
    levelEnd = candleEnd = snapDown(date > LAST_STORED ? LAST_STORED : date)
    candleStart = candleEnd
  } else if (from || to) {
    if (from && from > LAST_STORED)
      return json(res, { detail: `Range starts after the last stored session (${LAST_STORED})` }, 404)
    candleEnd = to && to <= LAST_STORED ? snapDown(to) : LAST_COMPLETE
    levelEnd = candleEnd
    candleStart = !from ? candleEnd : from < FIRST_STORED ? FIRST_STORED : snapUp(from)
    if (candleStart > candleEnd)
      return json(res, { detail: `No candles stored between ${from} and ${to}` }, 404)
  } else {
    // Session quick-picker / default "Latest" view. Never use an incomplete
    // stored "today" as the completed session — except when the user explicitly
    // asks for Today and wants to inspect the still-running session.
    if (view === 'prev') {
      levelEnd = completedDays[completedDays.length - 2] || LAST_COMPLETE
      candleEnd = levelEnd
    } else if (view === 'today' && !TODAY_COMPLETE && !isWeekend(TODAY)) {
      levelEnd = TODAY
      candleEnd = TODAY
    } else {
      levelEnd = LAST_COMPLETE
      candleEnd = (!TODAY_COMPLETE && !isWeekend(TODAY)) ? TODAY : LAST_COMPLETE
    }
    // TradingView-like window: show the last few sessions together.
    const recent = businessDays(FIRST_STORED, candleEnd, 5000)
    candleStart = recent[Math.max(0, recent.length - 3)]
  }
  const days = businessDays(candleStart, candleEnd)
  if (!days.length) return json(res, { detail: 'No candles stored for this window' }, 404)
  candleEnd = days[days.length - 1]
  candleStart = days[0]

  // One sheet per session drawn on the chart, each built from the session before
  // it. The session the chart is centred on also fills the flat fields.
  const capped = days.length > MAX_DAY_LEVELS
  const dayLevels = (capped ? days.slice(-MAX_DAY_LEVELS) : days).map((d) => daySheet(d, admin))
  const focused = dayLevels.find((d) => d.date === levelEnd) || dayLevels[dayLevels.length - 1] || null

  const isLatest = levelEnd === LAST_COMPLETE
  return json(res, {
    symbol,
    resolution,
    mode: candleStart === candleEnd ? 'day' : 'range',
    date: levelEnd,
    date_from: candleStart,
    date_to: candleEnd,
    first_date: FIRST_STORED,
    last_date: LAST_STORED,
    basis: focused ? focused.basis : null,
    day_type: focused ? focused.day_type : null,
    levels: focused ? focused.levels : [],
    day_levels: dayLevels,
    day_levels_capped: capped,
    next_levels: isLatest ? mockZones(levelEnd).zones.map((z) => asLevel(z, admin)) : [],
    next_session_date: isLatest ? NEXT_SESSION_DATE : null,
    next_session_kind: isLatest ? (NEXT_SESSION_DATE === TODAY ? 'today-open' : 'upcoming') : null,
    today: TODAY,
    last_complete_date: LAST_COMPLETE,
    session_complete: isLatest,
    view,
    server_time: istNow().toISOString(),
    candles: days.flatMap((d) => dayBars(d, resolution)),
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
