import { Activity, CalendarDays, Gauge, TrendingDown } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApi, fmtNum, fmtPct } from '../lib/hooks.js'
import { endpoints } from '../lib/api.js'
import { useSymbol, withSymbol } from '../lib/symbol.jsx'
import { Card, Empty, ErrorState, Note, Skeleton, TableWrap, Td, Th } from '../components/ui.jsx'

const tooltipStyle = {
  contentStyle: {
    background: '#0f1528',
    border: '1px solid rgba(148,163,184,.18)',
    borderRadius: 12,
    fontSize: 12,
    color: '#e8ecf7',
  },
  labelStyle: { color: '#94a3b8', fontSize: 11 },
}

function Meter({ value, tone = 'brand' }) {
  if (value === null || value === undefined) return <span className="text-slate-600">—</span>
  const colors = { brand: 'bg-brand-500', up: 'bg-emerald-500', warn: 'bg-amber-500' }[tone]
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-white/8">
        <div className={`h-full rounded-full ${colors}`} style={{ width: `${Math.min(100, Number(value))}%` }} />
      </div>
      <span className="num text-xs font-semibold text-slate-200">{fmtPct(value)}</span>
    </div>
  )
}

export default function GapCpr() {
  const { symbol } = useSymbol()
  const days = useApi(() => withSymbol(endpoints.dayStats, symbol), [symbol])
  const dash = useApi(() => withSymbol(endpoints.dashboard, symbol), [symbol])

  if (days.loading || dash.loading) return <Skeleton className="h-96 rounded-2xl" />
  if (days.error)
    return (
      <Card>
        <ErrorState error={days.error} onRetry={days.reload} />
      </Card>
    )

  const gapRows = days.data?.gap_fill || []
  const cprRows = dash.data?.cpr_matrix?.rows || []
  const dayRows = days.data?.day_type || []
  const weekday = days.data?.weekday || []
  const curve = gapRows.map((r) => ({ name: r.bucket, fill: r.fill_pct, trend: r.trend_pct, n: r.n }))

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card px-4 py-3.5">
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Sessions analysed</p>
          <p className="num mt-1 text-2xl font-bold text-slate-50">{fmtNum(days.data?.n)}</p>
        </div>
        <div className="card px-4 py-3.5">
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">First session</p>
          <p className="num mt-1 text-2xl font-bold text-slate-50">{days.data?.first_date || '—'}</p>
        </div>
        <div className="card px-4 py-3.5">
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Last session</p>
          <p className="num mt-1 text-2xl font-bold text-slate-50">{days.data?.last_date || '—'}</p>
        </div>
      </div>

      <Card
        title="Gap fill curve"
        icon={TrendingDown}
        subtitle="Fill = price touched the previous close at some point during the session."
      >
        {curve.length === 0 ? (
          <Empty title="Not enough sessions" hint="At least three completed sessions are needed." />
        ) : (
          <>
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={curve} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id="fillGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#22c55e" stopOpacity={0.5} />
                      <stop offset="100%" stopColor="#22c55e" stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.10)" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} unit="%" />
                  <Tooltip {...tooltipStyle} formatter={(v, n) => [`${v}%`, n === 'fill' ? 'Fill rate' : 'Trend day']} />
                  <Area type="monotone" dataKey="fill" stroke="#22c55e" fill="url(#fillGrad)" strokeWidth={2} />
                  <Area type="monotone" dataKey="trend" stroke="#6366f1" fill="url(#trendGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <TableWrap className="mt-3">
              <thead>
                <tr>
                  <Th>|Gap| %</Th>
                  <Th>n</Th>
                  <Th>Fill rate</Th>
                  <Th>Trend day</Th>
                  <Th>Avg range</Th>
                </tr>
              </thead>
              <tbody>
                {gapRows.map((r) => (
                  <tr key={r.bucket} className="transition hover:bg-white/3">
                    <Td className="num font-semibold">{r.bucket}</Td>
                    <Td className="num text-slate-400">{fmtNum(r.n)}</Td>
                    <Td>
                      <Meter value={r.fill_pct} tone="up" />
                    </Td>
                    <Td>
                      <Meter value={r.trend_pct} tone="brand" />
                    </Td>
                    <Td className="num text-slate-300">{fmtPct(r.avg_range_pct, 2)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          </>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="CPR day-type matrix" icon={Gauge} subtitle={dash.data?.cpr_matrix?.note}>
          {cprRows.length === 0 ? (
            <Empty title="No CPR sample yet" />
          ) : (
            <TableWrap>
              <thead>
                <tr>
                  <Th>Type</Th>
                  <Th>n</Th>
                  <Th>Trend day</Th>
                  <Th>Fill</Th>
                  <Th>Up day</Th>
                  <Th>Avg range</Th>
                </tr>
              </thead>
              <tbody>
                {cprRows.map((r) => (
                  <tr key={r.group} className="transition hover:bg-white/3">
                    <Td className="font-semibold">{r.group}</Td>
                    <Td className="num text-slate-400">{fmtNum(r.n)}</Td>
                    <Td>
                      <Meter value={r.trend_day_pct} tone="brand" />
                    </Td>
                    <Td>
                      <Meter value={r.fill_pct} tone="up" />
                    </Td>
                    <Td>
                      <Meter value={r.up_day_pct} tone="warn" />
                    </Td>
                    <Td className="num text-slate-300">{fmtPct(r.avg_range_pct, 2)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </Card>

        <Card title="By CPR day type (daily OHLC)" icon={Activity}>
          {dayRows.length === 0 ? (
            <Empty title="No sample yet" />
          ) : (
            <TableWrap>
              <thead>
                <tr>
                  <Th>Type</Th>
                  <Th>n</Th>
                  <Th>Trend day</Th>
                  <Th>Fill</Th>
                  <Th>Up</Th>
                </tr>
              </thead>
              <tbody>
                {dayRows.map((r) => (
                  <tr key={r.group} className="transition hover:bg-white/3">
                    <Td className="font-semibold">{r.group}</Td>
                    <Td className="num text-slate-400">{fmtNum(r.n)}</Td>
                    <Td>
                      <Meter value={r.trend_pct} tone="brand" />
                    </Td>
                    <Td>
                      <Meter value={r.fill_pct} tone="up" />
                    </Td>
                    <Td>
                      <Meter value={r.up_pct} tone="warn" />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </Card>
      </div>

      <Card title="Weekday behaviour" icon={CalendarDays}>
        {weekday.length === 0 ? (
          <Empty title="No sample yet" />
        ) : (
          <>
            <TableWrap>
              <thead>
                <tr>
                  <Th>Day</Th>
                  <Th>n</Th>
                  <Th>Trend day</Th>
                  <Th>Fill</Th>
                  <Th>Up</Th>
                  <Th>Avg range</Th>
                </tr>
              </thead>
              <tbody>
                {weekday.map((r) => (
                  <tr key={r.group} className="transition hover:bg-white/3">
                    <Td className="font-semibold">{r.group}</Td>
                    <Td className="num text-slate-400">{fmtNum(r.n)}</Td>
                    <Td>
                      <Meter value={r.trend_pct} tone="brand" />
                    </Td>
                    <Td>
                      <Meter value={r.fill_pct} tone="up" />
                    </Td>
                    <Td>
                      <Meter value={r.up_pct} tone="warn" />
                    </Td>
                    <Td className="num text-slate-300">{fmtPct(r.avg_range_pct, 2)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
            <Note>{days.data?.caveat}</Note>
          </>
        )}
      </Card>
    </div>
  )
}
