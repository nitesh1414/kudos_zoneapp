import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { useAuth } from './auth.jsx'

const SymbolContext = createContext(null)
const STORAGE_KEY = 'zoneapp.symbol'

/** Which symbol the market tabs are showing. Clients are pinned to their own
 * assigned symbol; administrators can switch between every tracked symbol. */
export function SymbolProvider({ children }) {
  const { user, isAdmin } = useAuth()
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

  // Only administrators may override; everyone else follows their account.
  const active = isAdmin && symbol ? symbol : user?.symbol || ''

  const value = useMemo(
    () => ({ symbol: active, setSymbol, tracked, canSwitch: !!isAdmin, refreshTracked: () =>
      api.get('/api/symbols').then((rows) => setTracked(rows || [])).catch(() => {}) }),
    [active, setSymbol, tracked, isAdmin],
  )
  return <SymbolContext.Provider value={value}>{children}</SymbolContext.Provider>
}

export const useSymbol = () => useContext(SymbolContext) || { symbol: '', tracked: [], canSwitch: false }

/** Append the active symbol to an API path. */
export function withSymbol(path, symbol) {
  if (!symbol) return path
  return `${path}${path.includes('?') ? '&' : '?'}symbol=${encodeURIComponent(symbol)}`
}
