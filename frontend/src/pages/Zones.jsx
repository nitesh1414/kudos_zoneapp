import { Layers, Ruler, Server } from 'lucide-react'
import { useApi, fmtNum, fmtPct, fmtSigned } from '../lib/hooks.js'
import { endpoints } from '../lib/api.js'
import { Badge, Card, Empty, ErrorState, Note, Skeleton, Stars, TableWrap, Td, Th } from '../components/ui.jsx'

export const resultTone = (result) =>
  ({ HELD: 'up', BROKE: 'down', TOUCHED: 'warn', 'NOT REACHED': 'neutral' }[result] || 'neutral')

const kindTone = { R: 'down', S: 'up', AT: 'warn' }
const kindRow = {
  R: 'bg-rose-500/4 hover:bg-rose-500/8',
  S: 'bg-emerald-500/4 hover:bg-emerald-500/8',
  AT: 'bg-amber-500/8 hover:bg-amber-500/12',
}
const kindText = { R: 'text-rose-400', S: 'text-emerald-400', AT: 'text-amber-400' }

export function ZoneRow({ zone, rate }) {
  const kind = zone.kind || (zone.label[0] === 'R' ? 'R' : zone.label[0] === 'S' ? 'S' : 'AT')
  return (
    <tr className={`transition ${kindRow[kind]}`}>
      <Td className={`font-bold ${kindText[kind]}`}>{zone.label}</Td>
      <Td className="num text-[15px] font-bold text-slate-50">{fmtNum(zone.key)}</Td>
      <Td className="num text-xs text-slate-400">
        {fmtNum(zone.lo)} – {fmtNum(zone.hi)}
      </Td>
      <Td>
        <Stars n={zone.stars} />
      </Td>
      <Td className="text-xs text-slate-400">{zone.key_name}</Td>
      <Td className="num text-slate-300">{fmtPct(rate?.touch_pct)}</Td>
      <Td className="num text-slate-300">{fmtPct(rate?.hold_pct)}</Td>
    </tr>
  )
}

export default function Zones() {
  const { data, error, loading, reload } = useApi(endpoints.dashboard)
  const rates = useApi(endpoints.zoneStats)

  const rateByStar = {}
  ;(rates.data?.by_stars || []).forEach((r) => (rateByStar[String(r.group)] = r))

  const zones = data?.zones
  const rows = [...(zones?.rows || [])].sort((a, b) => b.key - a.key)
  const basis = zones?.basis

  return (
    <div className="space-y-4">
      {loading && <Skeleton className="h-96 rounded-2xl" />}
      {error && (
        <Card>
          <ErrorState error={error} onRetry={reload} />
        </Card>
      )}
      {data && (
        <>
          {basis && (
            <Card title="Basis" icon={Ruler} right={<Badge tone="brand">{zones.day_type} CPR</Badge>}>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                {[
                  ['Date', basis.date],
                  ['High', fmtNum(basis.high, 2)],
                  ['Low', fmtNum(basis.low, 2)],
                  ['Close', fmtNum(basis.close, 2)],
                  ['Range', fmtPct(basis.range_pct, 2)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-xl bg-white/4 px-3 py-2.5 ring-1 ring-white/8">
                    <p className="text-[10.5px] tracking-wider text-slate-500 uppercase">{k}</p>
                    <p className="num mt-0.5 text-sm font-bold text-slate-100">{v}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card
            title="Zone map for the next session"
            icon={Layers}
            subtitle="Resistances above, the at-price zone in amber, supports below. Touch and hold columns are the historical rates for that star rating."
          >
            {rows.length === 0 ? (
              <Empty icon={Server} title="No zones available" hint="Ingest market data, then run the market-close job." />
            ) : (
              <>
                <TableWrap>
                  <thead>
                    <tr>
                      <Th>Zone</Th>
                      <Th>Level</Th>
                      <Th>Range</Th>
                      <Th>Strength</Th>
                      <Th>Built from</Th>
                      <Th>Touch rate</Th>
                      <Th>Held</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((z) => (
                      <ZoneRow key={z.label} zone={z} rate={rateByStar[String(z.stars)]} />
                    ))}
                  </tbody>
                </TableWrap>
                <Note>
                  Reference map from the last completed session — not a trade signal or forecast. Star rating tracks how
                  often a level is reached, not how often it holds.
                </Note>
              </>
            )}
          </Card>

          {rows.length > 0 && basis && (
            <Card title="Distance from previous close" icon={Ruler} subtitle={`Previous close ${fmtNum(basis.close, 2)}`}>
              <div className="space-y-1.5">
                {rows.map((z) => {
                  const max = Math.max(...rows.map((r) => Math.abs(r.dist_from_pdc ?? r.key - basis.close)), 1)
                  const dist = z.dist_from_pdc ?? z.key - basis.close
                  const width = (Math.abs(dist) / max) * 50
                  const up = dist >= 0
                  return (
                    <div key={z.label} className="flex items-center gap-3">
                      <span className={`w-8 shrink-0 text-xs font-bold ${kindText[z.kind]}`}>{z.label}</span>
                      <div className="relative h-6 flex-1 rounded-lg bg-white/3">
                        <div className="absolute inset-y-0 left-1/2 w-px bg-white/15" />
                        <div
                          className={`absolute inset-y-1 rounded ${up ? 'bg-rose-500/45' : 'bg-emerald-500/45'}`}
                          style={up ? { left: '50%', width: `${width}%` } : { right: '50%', width: `${width}%` }}
                        />
                      </div>
                      <span className="num w-20 shrink-0 text-right text-xs text-slate-400">{fmtSigned(dist, 1)}</span>
                    </div>
                  )
                })}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
