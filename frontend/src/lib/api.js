/** Thin fetch wrapper. Cookies carry the session, so every call is same-origin. */
export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const res = await fetch(path, {
    method,
    signal,
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }
  if (!res.ok) {
    const detail = data?.detail
    throw new ApiError(
      typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `Request failed (${res.status})`,
      res.status,
    )
  }
  return data
}

export const api = {
  get: (p, o) => request(p, o),
  post: (p, body) => request(p, { method: 'POST', body }),
  patch: (p, body) => request(p, { method: 'PATCH', body }),
  put: (p, body) => request(p, { method: 'PUT', body }),
  del: (p) => request(p, { method: 'DELETE' }),
}

export const endpoints = {
  me: '/api/me',
  login: '/api/auth/login',
  logout: '/api/auth/logout',
  dashboard: '/api/dashboard',
  health: '/api/health',
  zoneStats: '/api/stats/zones',
  dayStats: '/api/stats/days',
  sessions: (limit = 30) => `/api/sessions?limit=${limit}`,
  chartSession: '/api/chart/session',
  myBroker: '/api/my/broker',
  clients: '/api/admin/clients',
  client: (id) => `/api/admin/clients/${id}`,
  brokers: '/api/admin/brokers',
  broker: (id) => `/api/admin/brokers/${id}`,
  brokerTypes: '/api/admin/broker-types',
  brokerTest: (id) => `/api/admin/brokers/${id}/test`,
  brokerBackfill: (id) => `/api/admin/brokers/${id}/backfill`,
  brokerSeed: (id) => `/api/admin/brokers/${id}/seed`,
  jobRuns: (limit = 20) => `/api/admin/job-runs?limit=${limit}`,
  symbols: '/api/symbols',
  symbolCatalog: '/api/symbols/catalog',
  symbolAliases: '/api/admin/symbol-aliases',
  symbolAlias: (a) => `/api/admin/symbol-aliases/${encodeURIComponent(a)}`,
  adminSymbols: '/api/admin/symbols',
  adminSymbol: (s) => `/api/admin/symbols/${encodeURIComponent(s)}`,
  symbolSeed: (s) => `/api/admin/symbols/${encodeURIComponent(s)}/seed`,
  seedAll: '/api/admin/seed-all',
  seed: '/api/admin/seed',
  brokerToken: (id) => `/api/brokers/${id}/token`,
  brokerLoginUrl: (id) => `/api/admin/brokers/${id}/login-url`,
  brokerExchange: (id) => `/api/admin/brokers/${id}/exchange-token`,
  dataStatus: '/api/data-status',
  methodology: '/api/methodology',
  instruments: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null))
    return `/api/instruments${q.toString() ? `?${q}` : ''}`
  },
  instrumentStatus: '/api/instruments/status',
  underlyings: '/api/instruments/underlyings',
  expiries: (underlying) => `/api/instruments/expiries?underlying=${encodeURIComponent(underlying)}`,
  refreshInstruments: '/api/admin/instruments/refresh',
  syncHolidays: '/api/admin/holidays/sync',
  holidays: '/api/admin/holidays',
  holiday: (d) => `/api/admin/holidays/${d}`,
  giftNifty: '/api/admin/gift-nifty',
  marketClose: (force) => `/api/admin/jobs/market-close?force=${force ? 'true' : 'false'}`,
}
