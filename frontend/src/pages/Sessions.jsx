import { useState } from 'react'
import { CalendarRange } from 'lucide-react'
import { useApi, fmtDate, fmtNum } from '../lib/hooks.js'
import { endpoints } from '../lib/api.js'
import { Badge, Card, Empty, ErrorState, Select, Skeleton, TableWrap, Td, Th } from '../components/ui.jsx'

const dayTone = { NARROW: 'warn', NORMAL: 'brand', WIDE: 'up' }

export default function Sessions() {
  const [limit, setLimit] = useState(25)
  const { data, error, loading, reload } = useApi(() => endpoints.sessions(limit), [limit])

  return (
    <Card
      title="Recent sessions"
      icon={CalendarRange}
      subtitle="Zone outcomes per scored session: touched / held / broke."
      right={
        <Select className="w-28 py-1.5 text-xs" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          {[10, 25, 50, 100].map((n) => (
            <option key={n} value={n}>
              Last {n}
            </option>
          ))}
        </Select>
      }
    >
      {loading && <Skeleton className="h-64" />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && data.length === 0 && <Empty title="No scored sessions yet" hint="Run the market-close job to score sessions." />}
      {data && data.length > 0 && (
        <TableWrap>
          <thead>
            <tr>
              <Th>Date</Th>
              <Th>CPR type</Th>
              <Th>Gap %</Th>
              <Th>Open position</Th>
              <Th>Touched</Th>
              <Th>Held</Th>
              <Th>Broke</Th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => {
              const gap = Number(r.gap_pct ?? 0)
              return (
                <tr key={String(r.date)} className="transition hover:bg-white/3">
                  <Td className="num font-semibold whitespace-nowrap">{fmtDate(String(r.date).slice(0, 10))}</Td>
                  <Td>
                    <Badge tone={dayTone[r.day_type] || 'neutral'}>{r.day_type}</Badge>
                  </Td>
                  <Td className={`num font-semibold ${gap >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {gap > 0 ? '+' : ''}
                    {gap.toFixed(2)}
                  </Td>
                  <Td className="text-xs text-slate-400">{r.open_pos}</Td>
                  <Td className="num text-slate-200">{fmtNum(r.touched)}</Td>
                  <Td className="num text-emerald-400">{fmtNum(r.held)}</Td>
                  <Td className="num text-rose-400">{fmtNum(r.broke)}</Td>
                </tr>
              )
            })}
          </tbody>
        </TableWrap>
      )}
    </Card>
  )
}
