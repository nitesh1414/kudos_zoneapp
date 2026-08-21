import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, endpoints } from './api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setUser(await api.get(endpoints.me))
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const login = useCallback(
    async (username, password) => {
      await api.post(endpoints.login, { username, password })
      await refresh()
    },
    [refresh],
  )

  const logout = useCallback(async () => {
    try {
      await api.post(endpoints.logout)
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, logout, refresh, isAdmin: user?.role === 'admin' }),
    [user, loading, login, logout, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
