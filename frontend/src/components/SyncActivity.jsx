import { useEffect } from 'react'
import { History, Loader2, RefreshCw } from 'lucide-react'
import { fmtDateTime, fmtNum } from '../lib/hooks.js'
import { Badge, Button, Card, Empty, Skeleton, TableWrap, Td, Th } from './ui.jsx'

const runTone = { success: 'up', running: 'brand', failed: 'down' }

/** Seeding and market-close runs, so an admin can see what a job actually did. */
export default function SyncActivity({ runs }) {
  const rows = runs.data || []
  const busy = rows.some((r) => r.status === 'running')

  useEffect(() => {
    if (!busy) return
    const id = setInterval(runs.reload, 5000)
    return () => clearInterval(id)
  }, [busy, runs.reload])

  const summary = (r) => {
    const d = r.detail || {}
    if (d.error) return d.error
    const parts = []
    if (d.skipped) return d.reason || 'skipped — already running'
    if (d.bars_ingested !== undefined) parts.push(`${fmtNum(d.bars_ingested)} bars`)
    if (d.sessions_scored !== undefined) parts.push(`${fmtNum(d.sessions_scored)} sessions scored`)
    if (d.date_from) parts.push(`${d.date_from} → ${d.date_to}`)
    else if (d.days) parts.push(`${d.days} days`)
    return parts.join(' · ') || '—'
  }

  return (
    <Card
      title="Data sync activity"
      icon={History}
      subtitle="Seeding starts automatically whenever a token is saved."
      right={
        <Button variant="ghost" size="sm" icon={busy ? Loader2 : RefreshCw} onClick={runs.reload}>
          <span className="hidden sm:inline">{busy ? 'Running…' : 'Refresh'}</span>
        </Button>
      }
    >
      {runs.loading && <Skeleton className="h-24" />}
      {!runs.loading && rows.length === 0 && (
        <Empty icon={History} title="No runs yet" hint="Save a broker token or start a seed to see progress here." />
      )}
      {rows.length > 0 && (
        <TableWrap>
          <thead>
            <tr>
              <Th>Started</Th>
              <Th>Type</Th>
              <Th>Connection</Th>
              <Th>Symbol</Th>
              <Th>Status</Th>
              <Th>Result</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.id}-${r.kind}`} className="transition hover:bg-white/3">
                <Td className="num text-xs whitespace-nowrap text-slate-400">{fmtDateTime(r.started_at)}</Td>
                <Td className="text-xs">{r.kind === 'seed' ? 'Seed' : 'Market close'}</Td>
                <Td className="text-xs">{r.broker_name || `#${r.broker_id}`}</Td>
                <Td className="num text-xs">{r.symbol}</Td>
                <Td>
                  <Badge tone={runTone[r.status] || 'neutral'}>{r.status}</Badge>
                </Td>
                <Td className="text-xs text-slate-400">{summary(r)}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Card>
  )
}

