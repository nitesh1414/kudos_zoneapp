import {
  Activity, ArrowDownRight, ArrowUpRight, CalendarCheck, Database, Gauge, Info, Layers, Plug, Radar, Server, Timer,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApi, fmtDate, fmtDateTime, fmtNum, fmtPct, fmtSigned } from '../lib/hooks.js'
import { endpoints } from '../lib/api.js'
import { useSymbol, withSymbol } from '../lib/symbol.jsx'
import { useAuth } from '../lib/auth.jsx'
import { Badge, Button, Card, Empty, ErrorState, Skeleton, Stars, Stat, TableWrap, Td, Th } from '../components/ui.jsx'
import { ZoneRow, resultTone } from './Zones.jsx'

function StatsRow() {
  const { symbol } = useSymbol()
  const { data, loading } = useApi(() => withSymbol(endpoints.health, symbol), [symbol])
  if (loading)
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-[74px] rounded-2xl" />
        ))}
      </div>
    )
  const connected = data?.broker && data.broker !== 'Not connected'
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <Stat icon={Database} tone="brand" label="Data in database" value={fmtNum(data?.bars)} hint="Raw intraday candles" />
      <Stat icon={CalendarCheck} tone="up" label="Sessions scored" value={fmtNum(data?.sessions)} hint="Completed & evaluated" />
      <Stat icon={Radar} label="Zone observations" value={fmtNum(data?.zone_observations)} hint="Outcome records" />
      <Stat icon={Plug} tone={connected ? 'up' : 'down'} label="Broker" value={data?.broker || '—'} hint={connected ? 'Connected' : 'No broker assigned'} />
      <Stat icon={Server} label="Symbol" value={data?.symbol || '—'} hint="Assigned to your account" />
      <Stat
        icon={Timer}
        label="Server time"
        value={data?.server_time ? new Date(data.server_time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—'}
        hint={data?.server_time ? `${fmtDate(data.server_time)} · Asia/Kolkata` : 'Asia/Kolkata'}
      />
    </div>
  )
}

function GiftNifty({ gift }) {
  if (!gift) return null
  const up = Number(gift.gap_pct) >= 0
  const Icon = up ? ArrowUpRight : ArrowDownRight
  return (
    <Card title="GIFT Nifty snapshot" icon={Activity} subtitle={`Captured ${fmtDateTime(gift.captured_at)}`}>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Last traded</p>
          <p className="num mt-1 text-2xl font-bold text-slate-50">{fmtNum(gift.ltp, 1)}</p>
        </div>
        <div>
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Previous close</p>
          <p className="num mt-1 text-2xl font-bold text-slate-300">{fmtNum(gift.pdc, 1)}</p>
        </div>
        <div>
          <p className="text-[11px] tracking-wider text-slate-500 uppercase">Implied gap</p>
          <p className={`num mt-1 flex items-center gap-1 text-2xl font-bold ${up ? 'text-emerald-400' : 'text-rose-400'}`}>
            <Icon size={20} />
            {fmtSigned(gift.gap_pct)}%
          </p>
          <p className="num text-xs text-slate-500">{fmtSigned(gift.gap_pts, 1)} pts</p>
        </div>
      </div>
    </Card>
  )
}

function BasisCard({ zones }) {
  const basis = zones?.basis
  if (!basis) return null
  const items = [
    ['Basis date', fmtDate(basis.date)],
    ['High', fmtNum(basis.high, 2)],
    ['Low', fmtNum(basis.low, 2)],
    ['Close', fmtNum(basis.close, 2)],
    ['Range', fmtPct(basis.range_pct, 2)],
    ['CPR width', fmtPct(basis.cpr_pct, 2)],
  ]
  return (
    <Card
      title="Last completed session"
      icon={Gauge}
      right={<Badge tone="brand">{zones?.day_type || '—'} CPR</Badge>}
      subtitle="Zones for the next session are locked to these values."
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
        {items.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between border-b border-white/5 py-2 last:border-0">
            <dt className="text-xs text-slate-500">{k}</dt>
            <dd className="num text-sm font-semibold text-slate-100">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

function RecapCard({ recap, match, showStars }) {
  if (!recap) return null
  const a = recap.actuals
  const up = Number(a.change_pct) >= 0
  return (
    <Card
      title={`Session recap · ${fmtDate(recap.date)}`}
      icon={CalendarCheck}
      right={
        <Badge tone={up ? 'up' : 'down'}>
          {up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />} {fmtSigned(a.change_pct)}%
        </Badge>
      }
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ['Open', a.open],
          ['High', a.high],
          ['Low', a.low],
          ['Close', a.close],
        ].map(([k, v]) => (
          <div key={k} className="rounded-xl bg-white/4 px-3 py-2.5 ring-1 ring-white/8">
            <p className="text-[10.5px] tracking-wider text-slate-500 uppercase">{k}</p>
            <p className="num mt-0.5 text-[15px] font-bold text-slate-100">{fmtNum(v, 2)}</p>
          </div>
        ))}
      </div>
      <p className="mt-3.5 text-[13px] leading-relaxed text-slate-400">{recap.commentary}</p>
      {match && (
        <div className="mt-3.5 rounded-xl border border-white/8 bg-white/3 px-3.5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="brand">{match.basis_cpr_type}</Badge>
            <Badge tone={match.actual?.filled ? 'up' : 'warn'}>{match.actual?.filled ? 'Gap filled' : 'Gap not filled'}</Badge>
            <Badge tone={match.actual?.trend_day ? 'warn' : 'neutral'}>
              {match.actual?.trend_day ? 'Trend day' : 'Non-trend day'}
            </Badge>
          </div>
          <p className="mt-2 text-[12.5px] leading-relaxed text-slate-400">{match.commentary}</p>
        </div>
      )}
      {recap.zones?.length > 0 && (
        <TableWrap className="mt-3">
          <thead>
            <tr>
              <Th>Zone</Th>
              <Th>Level</Th>
              <Th>Built from</Th>
              {showStars && <Th>Strength</Th>}
              <Th>Result</Th>
            </tr>
          </thead>
          <tbody>
            {recap.zones.map((z) => (
              <tr key={z.label} className="transition hover:bg-white/3">
                <Td className="font-bold">{z.label}</Td>
                <Td className="num">{fmtNum(z.key)}</Td>
                <Td className="text-xs text-slate-400">{z.key_name}</Td>
                {showStars && (
                  <Td>
                    <Stars n={z.stars} />
                  </Td>
                )}
                <Td>
                  <Badge tone={resultTone(z.result)}>{z.result}</Badge>
                </Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Card>
  )
}

export default function Overview() {
  const { isAdmin } = useAuth()
  const { symbol } = useSymbol()
  const { data, error, loading, reload } = useApi(() => withSymbol(endpoints.dashboard, symbol), [symbol])
  const rates = useApi(() => withSymbol(endpoints.zoneStats, symbol), [symbol])

  const rateByStar = {}
  ;(rates.data?.by_stars || []).forEach((r) => (rateByStar[String(r.group)] = r))
  const rows = data?.zones?.rows || []
  const preview = [...rows].sort((a, b) => b.key - a.key).slice(0, 5)

  return (
    <div className="space-y-4">
      <StatsRow />
      {loading && <Skeleton className="h-64 rounded-2xl" />}
      {error && (
        <Card>
          <ErrorState error={error} onRetry={reload} />
        </Card>
      )}
      {data && (
        <>
          <div className="grid gap-4 xl:grid-cols-2">
            <BasisCard zones={data.zones} />
            <GiftNifty gift={data.gift_nifty} />
          </div>

          <Card
            title="Next-session zones"
            icon={Layers}
            subtitle="Top levels around the last close, ordered high to low."
            right={
              <Link to="/dashboard/zones">
                <Button variant="ghost" size="sm">
                  View all
                </Button>
              </Link>
            }
          >
            {preview.length === 0 ? (
              <Empty icon={Server} title="No levels yet" hint="Connect a broker and run the market-close job to build zones." />
            ) : (
              <TableWrap>
                <thead>
                  <tr>
                    <Th>Zone</Th>
                    <Th>Level</Th>
                    <Th>Range</Th>
                    {isAdmin && <Th>Strength</Th>}
                    <Th>Built from</Th>
                    <Th>Touch</Th>
                    <Th>Held</Th>
                  </tr>
                </thead>
                <tbody>
                  {preview.map((z) => (
                    <ZoneRow key={z.label} zone={z} rate={rateByStar[String(z.stars)]} showStars={isAdmin} />
                  ))}
                </tbody>
              </TableWrap>
            )}
          </Card>

          <RecapCard recap={data.session_recap} match={data.match_check} showStars={isAdmin} />

          <div className="card animate-rise flex gap-3 px-4 py-3.5 sm:px-5">
            <Info size={16} className="mt-0.5 shrink-0 text-slate-500" />
            <p className="text-[11.5px] leading-relaxed text-slate-500 italic">
              Base rates on this page describe what happened in the stored sample. They are not forecasts. The
              random-line baseline measured on this dataset was about 62% bounce-on-touch, so compare zone numbers
              against 62, not against 50.
              {isAdmin && ' Star rating tracks how often a level is REACHED, not how often it holds.'}
            </p>
          </div>
        </>
      )}
    </div>
  )
}
