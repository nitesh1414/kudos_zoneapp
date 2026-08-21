import { useMemo, useState } from 'react'
import { CalendarRange, CandlestickChart, CheckCheck, DatabaseZap, PlayCircle, Square, SquareCheckBig } from 'lucide-react'
import { api, endpoints } from '../../lib/api.js'
import { useApi, fmtDate, fmtNum } from '../../lib/hooks.js'
import SyncActivity from '../../components/SyncActivity.jsx'
import { useSymbol } from '../../lib/symbol.jsx'
import { Badge, Button, Card, Empty, Field, Input, Skeleton } from '../../components/ui.jsx'

// "Past day", "past month" … expressed as trailing day counts the API accepts.
const PRESETS = [
  { id: 'today', label: 'Today', days: 1, hint: 'Since yesterday' },
  { id: 'week', label: 'Past week', days: 7 },
  { id: 'month', label: 'Past month', days: 30 },
  { id: 'quarter', label: 'Past 3 months', days: 90 },
  { id: 'half', label: 'Past 6 months', days: 182 },
  { id: 'year', label: 'Past year', days: 365 },
  { id: 'twoyears', label: 'Past 2 years', days: 730 },
  { id: 'fiveyears', label: 'Past 5 years', days: 1825 },
  { id: 'custom', label: 'Custom range', days: null },
]

const isoDaysAgo = (days) => {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

export default function Seeding() {
  const { resolutions } = useSymbol()
  const TIMEFRAMES = resolutions.length ? resolutions : ['15', 'D']
  const symbols = useApi(endpoints.symbols)
  const runs = useApi(() => endpoints.jobRuns(20), [])
  const [preset, setPreset] = useState('month')
  const [from, setFrom] = useState(isoDaysAgo(30))
  const [to, setTo] = useState(new Date().toISOString().slice(0, 10))
  const [picked, setPicked] = useState([]) // empty = every tracked symbol
  const [timeframes, setTimeframes] = useState([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const tracked = useMemo(() => (symbols.data || []).filter((s) => s.active !== false), [symbols.data])
  const active = PRESETS.find((p) => p.id === preset)
  const custom = preset === 'custom'
  const targets = picked.length ? picked : tracked.map((s) => s.symbol)

  const windowLabel = custom
    ? `${fmtDate(from)} → ${fmtDate(to)}`
    : `${fmtDate(isoDaysAgo(active.days))} → ${fmtDate(new Date().toISOString().slice(0, 10))}`

  const toggleSymbol = (symbol) =>
    setPicked((cur) => (cur.includes(symbol) ? cur.filter((s) => s !== symbol) : [...cur, symbol]))

  const toggleTimeframe = (tf) =>
    setTimeframes((cur) => (cur.includes(tf) ? cur.filter((t) => t !== tf) : [...cur, tf]))

  const start = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const body = picked.length ? { symbols: picked } : {}
      if (custom) Object.assign(body, { date_from: from, date_to: to })
      else body.days = active.days
      if (timeframes.length) body.resolutions = timeframes
      const res = await api.post(endpoints.seed, body)
      setMsg({ ok: true, text: res.seed_message })
      setTimeout(runs.reload, 800)
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title="Seed market data"
        icon={DatabaseZap}
        subtitle="Fetch candles for a chosen period and rebuild zones, outcomes and base rates from them."
      >
        <div className="space-y-5">
          <div>
            <p className="mb-2 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Period</p>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => {
                    setPreset(p.id)
                    if (p.days) setFrom(isoDaysAgo(p.days))
                  }}
                  className={`rounded-xl px-3.5 py-2 text-xs font-semibold ring-1 transition ${
                    preset === p.id
                      ? 'bg-brand-600 text-white ring-brand-500 shadow-lg shadow-brand-600/25'
                      : 'bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {custom && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="From">
                <Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
              </Field>
              <Field label="To">
                <Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
              </Field>
            </div>
          )}

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Symbols</p>
              <div className="flex gap-1.5">
                <Button variant="subtle" size="sm" icon={CheckCheck} onClick={() => setPicked([])}>
                  All tracked
                </Button>
                <Button variant="subtle" size="sm" icon={Square} onClick={() => setPicked(tracked.map((s) => s.symbol))}>
                  Select individually
                </Button>
              </div>
            </div>
            {symbols.loading && <Skeleton className="h-16" />}
            {!symbols.loading && tracked.length === 0 && (
              <Empty icon={CandlestickChart} title="No symbols tracked yet" hint="Add symbols under Market symbols first." />
            )}
            {tracked.length > 0 && (
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {tracked.map((s) => {
                  const on = picked.length === 0 || picked.includes(s.symbol)
                  return (
                    <button
                      key={s.symbol}
                      onClick={() => toggleSymbol(s.symbol)}
                      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-left ring-1 transition ${
                        on ? 'bg-brand-500/10 ring-brand-500/30' : 'bg-white/4 ring-white/10 hover:bg-white/8'
                      }`}
                    >
                      {on ? (
                        <SquareCheckBig size={16} className="shrink-0 text-brand-400" />
                      ) : (
                        <Square size={16} className="shrink-0 text-slate-600" />
                      )}
                      <span className="min-w-0">
                        <span className="num block truncate text-[12.5px] font-semibold text-slate-100">{s.symbol}</span>
                        <span className="block truncate text-[11px] text-slate-500">
                          {fmtNum(s.bars)} bars · {fmtNum(s.sessions)} sessions
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
            {picked.length === 0 && tracked.length > 0 && (
              <p className="mt-2 text-[11.5px] text-slate-500">
                Nothing selected — every tracked symbol will be fetched.
              </p>
            )}
          </div>

          <div>
            <p className="mb-2 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">
              Timeframes <span className="normal-case text-slate-600">(optional override)</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {TIMEFRAMES.map((tf) => {
                const on = timeframes.includes(tf)
                return (
                  <button
                    key={tf}
                    onClick={() => toggleTimeframe(tf)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold ring-1 transition ${
                      on ? 'bg-brand-600 text-white ring-brand-500' : 'bg-white/5 text-slate-300 ring-white/10'
                    }`}
                  >
                    {tf === 'D' ? 'Daily' : `${tf}m`}
                  </button>
                )
              })}
            </div>
            <p className="mt-2 text-[11.5px] text-slate-500">
              Leave empty to use each symbol's own timeframes. 15-minute candles are always included — the zone
              engine is built on them.
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/4 px-4 py-3.5">
            <div className="flex items-center gap-3">
              <CalendarRange size={18} className="text-brand-400" />
              <div>
                <p className="text-[13px] font-semibold text-slate-100">{windowLabel}</p>
                <p className="text-[11.5px] text-slate-500">
                  {targets.length} symbol{targets.length === 1 ? '' : 's'} ·{' '}
                  {timeframes.length ? timeframes.join(', ') : 'default timeframes'}
                </p>
              </div>
            </div>
            <Button icon={PlayCircle} loading={busy} disabled={targets.length === 0} onClick={start}>
              Start seeding
            </Button>
          </div>

          {msg && (
            <p
              className={`rounded-xl px-3.5 py-3 text-[13px] ring-1 ${
                msg.ok ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/25' : 'bg-rose-500/10 text-rose-300 ring-rose-500/25'
              }`}
            >
              {msg.text}
            </p>
          )}

          <p className="text-[11.5px] leading-relaxed text-slate-500 italic">
            Seeding is idempotent: candles are upserted, so re-running a period repairs gaps instead of duplicating
            data. Long ranges take a few minutes per symbol — progress appears below.
            <Badge tone="neutral" className="ml-2">
              Runs in the background
            </Badge>
          </p>
        </div>
      </Card>

      <SyncActivity runs={runs} />
    </div>
  )
}
