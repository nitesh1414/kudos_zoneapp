import { useEffect, useMemo, useState } from 'react'
import {
  Boxes, CalendarClock, CircleDollarSign, Layers, RefreshCw, Search, TrendingUp,
} from 'lucide-react'
import { api, endpoints } from '../../lib/api.js'
import { useApi, fmtDate, fmtDateTime, fmtNum } from '../../lib/hooks.js'
import {
  Badge, Button, Card, Empty, ErrorState, Input, Select, Skeleton, TableWrap, Td, Th,
} from '../../components/ui.jsx'

const TYPE_TONE = { INDEX: 'brand', EQ: 'neutral', FUT: 'warn', CE: 'up', PE: 'down' }

export default function Instruments() {
  const status = useApi(endpoints.instrumentStatus)
  const [query, setQuery] = useState('')
  const [type, setType] = useState('')
  const [underlying, setUnderlying] = useState('')
  const [expiry, setExpiry] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const unders = useApi(endpoints.underlyings)
  const expiries = useApi(() => (underlying ? endpoints.expiries(underlying) : endpoints.instrumentStatus), [underlying])
  const results = useApi(
    () => endpoints.instruments({ q: query, type, underlying, expiry, limit: 200 }),
    [query, type, underlying, expiry],
  )

  useEffect(() => setExpiry(''), [underlying])

  const expiryRows = underlying && Array.isArray(expiries.data) ? expiries.data : []
  const items = results.data?.items || []
  const types = results.data?.types || ['INDEX', 'EQ', 'FUT', 'CE', 'PE']

  const refresh = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const res = await api.post(endpoints.refreshInstruments)
      setMsg({ ok: true, text: res.message })
      setTimeout(() => {
        status.reload()
        unders.reload()
        results.reload()
      }, 4000)
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const counts = useMemo(() => {
    const map = {}
    ;(status.data?.by_type || []).forEach((r) => (map[r.instrument_type] = r.n))
    return map
  }, [status.data])

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Contracts stored', value: fmtNum(status.data?.total), icon: Boxes, tone: 'text-brand-400 bg-brand-500/10' },
          { label: 'Futures', value: fmtNum(counts.FUT || 0), icon: TrendingUp, tone: 'text-amber-400 bg-amber-500/10' },
          { label: 'Options', value: fmtNum((counts.CE || 0) + (counts.PE || 0)), icon: Layers, tone: 'text-emerald-400 bg-emerald-500/10' },
          { label: 'Cash & indices', value: fmtNum((counts.EQ || 0) + (counts.INDEX || 0)), icon: CircleDollarSign, tone: 'text-sky-400 bg-sky-500/10' },
        ].map(({ label, value, icon: Icon, tone }) => (
          <div key={label} className="card animate-rise flex items-center gap-3.5 px-4 py-3.5">
            <div className={`grid size-10 place-items-center rounded-xl ${tone}`}>
              <Icon size={18} />
            </div>
            <div className="min-w-0">
              <p className="text-[11px] tracking-wider text-slate-500 uppercase">{label}</p>
              <p className="num text-xl font-bold text-slate-50">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {msg && (
        <div className={`card animate-rise px-4 py-3 text-[13px] ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`}>
          {msg.text}
        </div>
      )}

      <Card
        title="Instrument master"
        icon={Boxes}
        subtitle="Every contract the provider publishes — lot size, tick size, expiry, strike and option type — stored in the database and refreshed in the background."
        right={
          <div className="flex items-center gap-2">
            {status.data?.stale && <Badge tone="warn">Stale</Badge>}
            <Button variant="ghost" size="sm" icon={RefreshCw} loading={busy} onClick={refresh}>
              <span className="hidden sm:inline">Refresh master</span>
            </Button>
          </div>
        }
      >
        <p className="mb-4 text-[11.5px] text-slate-500">
          {status.data?.last_sync?.finished_at
            ? `Last downloaded ${fmtDateTime(status.data.last_sync.finished_at)} · ${fmtNum(status.data.last_sync.total)} contracts`
            : 'Not downloaded yet — the headline indices are seeded so the pickers still work.'}
          {status.data?.last_sync?.errors && Object.keys(status.data.last_sync.errors).length > 0 && (
            <span className="text-amber-400">
              {' '}
              · {Object.keys(status.data.last_sync.errors).length} segment(s) failed last time
            </span>
          )}
        </p>

        <div className="mb-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <div className="relative">
            <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-500" />
            <Input className="pl-9" placeholder="Search symbol or name…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <Select value={underlying} onChange={(e) => setUnderlying(e.target.value)}>
            <option value="">All underlyings</option>
            {(unders.data || []).map((u) => (
              <option key={u.underlying} value={u.underlying}>
                {u.underlying} — {fmtNum(u.options)} options · lot {u.lot_size ?? '—'}
              </option>
            ))}
          </Select>
          <Select value={expiry} onChange={(e) => setExpiry(e.target.value)} disabled={!underlying}>
            <option value="">{underlying ? 'All expiries' : 'Pick an underlying first'}</option>
            {expiryRows.map((e) => (
              <option key={e.expiry_date} value={e.expiry_date}>
                {fmtDate(e.expiry_date)} — {fmtNum(e.contracts)} contracts
              </option>
            ))}
          </Select>
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
        </div>

        {underlying && expiryRows.length > 0 && (
          <div className="scrollbar-thin mb-4 -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
            {expiryRows.map((e) => (
              <button
                key={e.expiry_date}
                onClick={() => setExpiry(expiry === e.expiry_date ? '' : e.expiry_date)}
                className={`shrink-0 rounded-xl px-3.5 py-2 text-left ring-1 transition ${
                  expiry === e.expiry_date ? 'bg-brand-600 text-white ring-brand-500' : 'bg-white/5 text-slate-300 ring-white/10'
                }`}
              >
                <span className="num block text-[12.5px] font-semibold">{fmtDate(e.expiry_date)}</span>
                <span className="block text-[10.5px] opacity-80">
                  lot {e.lot_size ?? '—'} · {fmtNum(e.calls)}C / {fmtNum(e.puts)}P
                </span>
              </button>
            ))}
          </div>
        )}

        {results.loading && <Skeleton className="h-48" />}
        {results.error && <ErrorState error={results.error} onRetry={results.reload} />}
        {results.data && items.length === 0 && (
          <Empty icon={Boxes} title="No contracts match" hint="Refresh the master, or widen the filters." />
        )}
        {items.length > 0 && (
          <TableWrap>
            <thead>
              <tr>
                <Th>Symbol</Th>
                <Th>Name</Th>
                <Th>Type</Th>
                <Th>Underlying</Th>
                <Th>Expiry</Th>
                <Th>Strike</Th>
                <Th>Lot size</Th>
                <Th>Tick</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.symbol} className="transition hover:bg-white/3">
                  <Td className="num text-xs font-semibold whitespace-nowrap text-slate-100">{i.symbol}</Td>
                  <Td className="max-w-[16rem] truncate text-xs text-slate-400">{i.name}</Td>
                  <Td>
                    <Badge tone={TYPE_TONE[i.instrument_type] || 'neutral'}>{i.instrument_type}</Badge>
                  </Td>
                  <Td className="num text-xs">{i.underlying || '—'}</Td>
                  <Td className="num text-xs whitespace-nowrap">{i.expiry_date ? fmtDate(i.expiry_date) : '—'}</Td>
                  <Td className="num text-xs">{i.strike ? fmtNum(i.strike) : '—'}</Td>
                  <Td className="num text-xs font-semibold text-slate-200">{i.lot_size ?? '—'}</Td>
                  <Td className="num text-xs text-slate-400">{i.tick_size ?? '—'}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <Card title="Underlyings with derivatives" icon={CalendarClock}
            subtitle="Lot size and the next expiry for everything that has a futures or options chain.">
        {unders.loading && <Skeleton className="h-32" />}
        {unders.data && unders.data.length === 0 && (
          <Empty icon={CalendarClock} title="No derivatives stored yet" hint="Refresh the instrument master to pull them in." />
        )}
        {unders.data && unders.data.length > 0 && (
          <TableWrap>
            <thead>
              <tr>
                <Th>Underlying</Th>
                <Th>Lot size</Th>
                <Th>Futures</Th>
                <Th>Options</Th>
                <Th>Expiries</Th>
                <Th>Next expiry</Th>
              </tr>
            </thead>
            <tbody>
              {unders.data.slice(0, 60).map((u) => (
                <tr key={u.underlying} className="cursor-pointer transition hover:bg-white/3"
                    onClick={() => setUnderlying(u.underlying)}>
                  <Td className="num text-xs font-semibold text-slate-100">{u.underlying}</Td>
                  <Td className="num text-xs font-semibold text-slate-200">{u.lot_size ?? '—'}</Td>
                  <Td className="num text-xs">{fmtNum(u.futures)}</Td>
                  <Td className="num text-xs">{fmtNum(u.options)}</Td>
                  <Td className="num text-xs">{fmtNum(u.expiries)}</Td>
                  <Td className="num text-xs">{u.next_expiry ? fmtDate(u.next_expiry) : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </div>
  )
}
