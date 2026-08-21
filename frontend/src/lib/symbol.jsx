import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { useAuth } from './auth.jsx'

const SymbolContext = createContext(null)
const STORAGE_KEY = 'zoneapp.symbol'

/** Which symbol the market tabs are showing, plus the database-backed catalogue
 * (watchlist, aliases, timeframes) every picker in the app is built from. */
const EMPTY_CATALOG = { symbols: [], aliases: {}, resolutions: [], default: '' }

export function SymbolProvider({ children }) {
  const { user } = useAuth()
  const [symbol, setSymbolState] = useState(() => localStorage.getItem(STORAGE_KEY) || '')
  const [catalog, setCatalog] = useState(EMPTY_CATALOG)

  // One database-backed catalogue drives every symbol and timeframe picker,
  // so a symbol added in the admin panel appears everywhere without a reload.
  const loadCatalog = useCallback(() => {
    if (!user) return Promise.resolve()
    return api
      .get('/api/symbols/catalog')
      .then((data) => setCatalog({ ...EMPTY_CATALOG, ...(data || {}) }))
      .catch(() => setCatalog(EMPTY_CATALOG))
  }, [user])

  useEffect(() => {
    loadCatalog()
  }, [loadCatalog])

  const setSymbol = useCallback((next) => {
    setSymbolState(next || '')
    if (next) localStorage.setItem(STORAGE_KEY, next)
    else localStorage.removeItem(STORAGE_KEY)
  }, [])

  // Accounts are not tied to a symbol: anyone signed in can view any tracked
  // one. The database decides which symbol a fresh visitor lands on.
  const tracked = catalog.symbols || []
  const known = tracked.map((t) => t.symbol)
  const active = (symbol && known.includes(symbol) && symbol) || catalog.default || known[0] || ''

  const value = useMemo(
    () => ({
      symbol: active,
      setSymbol,
      tracked,
      aliases: catalog.aliases || {},
      resolutions: catalog.resolutions || [],
      defaultSymbol: catalog.default || '',
      label: tracked.find((t) => t.symbol === active)?.label || '',
      canSwitch: known.length > 0,
      refreshTracked: loadCatalog,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [active, setSymbol, catalog, known.length, loadCatalog],
  )
  return <SymbolContext.Provider value={value}>{children}</SymbolContext.Provider>
}

export const useSymbol = () =>
  useContext(SymbolContext) || { symbol: '', tracked: [], aliases: {}, resolutions: [], canSwitch: false }

/** Append the active symbol to an API path. */
export function withSymbol(path, symbol) {
  if (!symbol) return path
  return `${path}${path.includes('?') ? '&' : '?'}symbol=${encodeURIComponent(symbol)}`
}
