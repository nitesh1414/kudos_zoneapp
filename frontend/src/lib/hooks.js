import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'

/** Small data-fetching hook: { data, error, loading, reload }. */
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const alive = useRef(true)

  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }))
    try {
      const data = await api.get(typeof path === 'function' ? path() : path)
      if (alive.current) setState({ data, error: null, loading: false })
    } catch (error) {
      if (alive.current) setState({ data: null, error, loading: false })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    alive.current = true
    reload()
    // A single 'Refresh' control in the header refetches every mounted panel.
    window.addEventListener('zoneapp:refresh', reload)
    return () => {
      alive.current = false
      window.removeEventListener('zoneapp:refresh', reload)
    }
  }, [reload])

  return { ...state, reload }
}

export const fmtNum = (v, digits = 0) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? '—'
    : Number(v).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export const fmtPct = (v, digits = 1) =>
  v === null || v === undefined || v === '' ? '—' : `${Number(v).toFixed(digits)}%`

export const fmtSigned = (v, digits = 2) =>
  v === null || v === undefined ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(digits)}`

export const fmtDate = (value) => {
  if (!value) return '—'
  const d = new Date(String(value).length <= 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 10)
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

export const fmtDateTime = (value) => {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export const initials = (name = '') =>
  name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('') || '?'
