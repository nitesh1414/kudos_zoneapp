import { BarChart3, Compass, Star, Target } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApi, fmtNum, fmtPct } from '../lib/hooks.js'
import { endpoints } from '../lib/api.js'
import { Card, Empty, ErrorState, Note, Skeleton, Stars, TableWrap, Td, Th } from '../components/ui.jsx'

const tooltipStyle = {
  contentStyle: {
    background: '#0f1528',
    border: '1px solid rgba(148,163,184,.18)',
    borderRadius: 12,
    fontSize: 12,
    color: '#e8ecf7',
  },
  labelStyle: { color: '#94a3b8', fontSize: 11 },
  cursor: { fill: 'rgba(148,163,184,.06)' },
}

function RateBar({ value, tone = 'brand' }) {
  if (value === null || value === undefined) return <span className="text-slate-600">—</span>
  const colors = { brand: 'bg-brand-500', up: 'bg-emerald-500', down: 'bg-rose-500', warn: 'bg-amber-500' }[tone]
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/8">
        <div className={`h-full rounded-full ${colors}`} style={{ width: `${Math.min(100, Number(value))}%` }} />
      </div>
      <span className="num text-xs font-semibold text-slate-200">{fmtPct(value)}</span>
    </div>
  )
}

function RateTable({ rows, firstHeader = 'Group', renderKey }) {
  if (!rows?.length) return <Empty title="No sample yet" hint="Base rates appear once sessions have been scored." />
  return (
    <TableWrap>
      <thead>
        <tr>
          <Th>{firstHeader}</Th>
          <Th>n</Th>
          <Th>Touch</Th>
          <Th>Bounce</Th>
          <Th>Break</Th>
          <Th>Held</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.group} className="transition hover:bg-white/3">
            <Td className="font-semibold">{renderKey ? renderKey(r.group) : r.group}</Td>
            <Td className="num text-slate-400">{fmtNum(r.n)}</Td>
            <Td>
              <RateBar value={r.touch_pct} tone="brand" />
            </Td>
            <Td>
              <RateBar value={r.bounce_pct} tone="up" />
            </Td>
            <Td>
              <RateBar value={r.break_pct} tone="down" />
            </Td>
            <Td>
              <RateBar value={r.hold_pct} tone="warn" />
            </Td>
          </tr>
        ))}
      </tbody>
    </TableWrap>
  )
}

export default function BaseRates() {
  const { data, error, loading, reload } = useApi(endpoints.zoneStats)

  if (loading) return <Skeleton className="h-96 rounded-2xl" />
  if (error)
    return (
      <Card>
        <ErrorState error={error} onRetry={reload} />
      </Card>
    )

  const byStars = data?.by_stars || [] // administrators only
  const chart = byStars.map((r) => ({
    name: `${r.group}★`,
    touch: r.touch_pct ?? 0,
    bounce: r.bounce_pct ?? 0,
    hold: r.hold_pct ?? 0,
  }))

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card px-4 py-3.5">
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Zone observations</p>
          <p className="num mt-1 text-2xl font-bold text-slate-50">{fmtNum(data?.n)}</p>
        </div>
        <div className="card px-4 py-3.5">
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Sessions in sample</p>
          <p className="num mt-1 text-2xl font-bold text-slate-50">{fmtNum(data?.sessions)}</p>
        </div>
        <div className="card px-4 py-3.5">
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Random-line baseline</p>
          <p className="num mt-1 text-2xl font-bold text-amber-400">≈ 62%</p>
        </div>
      </div>

      {chart.length === 0 && (
        <Card title="How to read these tables" icon={Target}>
          <p className="text-[13px] leading-relaxed text-slate-400">
            Touch is how often a zone was reached, bounce and break are what happened once it was reached, and held is
            how often the level was defended for the rest of the session. Always read them next to n — a high rate on a
            small sample means very little.
          </p>
        </Card>
      )}

      {chart.length > 0 && (
        <Card title="Bounce & touch rate by star rating" icon={BarChart3} subtitle="Amber line marks the 62% random-line baseline — compare bounce against it, not against 50.">
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} margin={{ top: 8, right: 8, left: -18, bottom: 0 }} barGap={4}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.10)" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} unit="%" />
                <Tooltip {...tooltipStyle} formatter={(v, n) => [`${v}%`, n]} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <ReferenceLine y={62} stroke="#f59e0b" strokeDasharray="5 4" />
                <Bar dataKey="touch" name="Touch" fill="#6366f1" radius={[5, 5, 0, 0]} />
                <Bar dataKey="bounce" name="Bounce" fill="#22c55e" radius={[5, 5, 0, 0]} />
                <Bar dataKey="hold" name="Held" fill="#38bdf8" radius={[5, 5, 0, 0]}>
                  {chart.map((_, i) => (
                    <Cell key={i} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {byStars.length > 0 && (
        <Card title="By zone strength" icon={Star} subtitle="Star rating is an administrator-only view.">
          <RateTable rows={byStars} firstHeader="Stars" renderKey={(g) => <Stars n={Number(g)} />} />
          <Note>{data?.baseline_note}</Note>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="By side" icon={Target} subtitle="Resistance, support and the at-price zone.">
          <RateTable rows={data?.by_side} firstHeader="Side" />
        </Card>
        <Card title="By CPR day type" icon={Compass}>
          <RateTable rows={data?.by_day_type} firstHeader="Day type" />
        </Card>
      </div>

      <Card title="By opening position" icon={Compass} subtitle="Where the session opened relative to the zone band.">
        <RateTable rows={data?.by_open_pos} firstHeader="Open position" />
        {byStars.length === 0 && <Note>{data?.baseline_note}</Note>}
      </Card>
    </div>
  )
}
