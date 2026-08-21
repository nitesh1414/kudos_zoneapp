import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { useAuth } from './auth.jsx'

const SymbolContext = createContext(null)
const STORAGE_KEY = 'zoneapp.symbol'

/** Which symbol the market tabs are showing. Clients are pinned to their own
 * assigned symbol; administrators can switch between every tracked symbol. */
export function SymbolProvider({ children }) {
  const { user } = useAuth()
  const [symbol, setSymbolState] = useState(() => localStorage.getItem(STORAGE_KEY) || '')
  const [tracked, setTracked] = useState([])

  useEffect(() => {
    if (!user) return
    api
      .get('/api/symbols')
      .then((rows) => setTracked(rows || []))
      .catch(() => setTracked([]))
  }, [user])

  const setSymbol = useCallback((next) => {
    setSymbolState(next || '')
    if (next) localStorage.setItem(STORAGE_KEY, next)
    else localStorage.removeItem(STORAGE_KEY)
  }, [])

  // Accounts are not tied to a symbol: anyone signed in can view any tracked
  // symbol. Fall back to the first tracked one until a choice is made.
  const known = tracked.map((t) => t.symbol)
  const active = (symbol && known.includes(symbol) && symbol) || known[0] || symbol || ''

  const value = useMemo(
    () => ({ symbol: active, setSymbol, tracked, canSwitch: known.length > 0, refreshTracked: () =>
      api.get('/api/symbols').then((rows) => setTracked(rows || [])).catch(() => {}) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [active, setSymbol, tracked, known.length],
  )
  return <SymbolContext.Provider value={value}>{children}</SymbolContext.Provider>
}

export const useSymbol = () => useContext(SymbolContext) || { symbol: '', tracked: [], canSwitch: false }

/** Append the active symbol to an API path. */
export function withSymbol(path, symbol) {
  if (!symbol) return path
  return `${path}${path.includes('?') ? '&' : '?'}symbol=${encodeURIComponent(symbol)}`
}
