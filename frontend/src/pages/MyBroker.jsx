import { useState } from 'react'
import { KeyRound, Plug, ShieldCheck, ShieldAlert } from 'lucide-react'
import { api, endpoints } from '../lib/api.js'
import { useApi, fmtDateTime } from '../lib/hooks.js'
import { Badge, Button, Card, Empty, ErrorState, Field, Input, Skeleton } from '../components/ui.jsx'

const statusTone = { valid: 'up', expiring: 'warn', expired: 'down', missing: 'down', unknown: 'neutral' }

export default function MyBroker() {
  const { data, error, loading, reload } = useApi(endpoints.myBroker)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const save = async (e) => {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    try {
      const res = await api.post(endpoints.brokerToken(data.id), { access_token: token.trim(), seed: true })
      setMsg({ ok: true, text: `${res.message || 'Token saved.'} ${res.seed_message || ''}`.trim() })
      setToken('')
      reload()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Skeleton className="h-64 rounded-2xl" />
  if (error)
    return (
      <Card>
        <ErrorState error={error} onRetry={reload} />
      </Card>
    )

  if (!data?.assigned)
    return (
      <Card title="My broker" icon={Plug}>
        <Empty icon={Plug} title="No broker assigned" hint={data?.notification || 'Contact your administrator to get a broker connection assigned to your account.'} />
      </Card>
    )

  const tone = statusTone[data.token_status] || 'neutral'
  const good = data.token_status === 'valid'

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Connection" icon={Plug} right={<Badge tone={tone}>{data.token_status}</Badge>}>
        <div className="flex items-start gap-3.5">
          <div className={`grid size-11 shrink-0 place-items-center rounded-2xl ${good ? 'bg-emerald-500/12 text-emerald-400' : 'bg-amber-500/12 text-amber-400'}`}>
            {good ? <ShieldCheck size={20} /> : <ShieldAlert size={20} />}
          </div>
          <div className="min-w-0">
            <p className="text-base font-bold text-slate-100">{data.name}</p>
            <p className="text-xs text-slate-500 capitalize">{data.broker_type}</p>
            <p className="mt-2 text-[13px] leading-relaxed text-slate-400">{data.notification}</p>
          </div>
        </div>
        <dl className="mt-4 space-y-1">
          {[
            ['Token updated', fmtDateTime(data.token_updated_at)],
            ['Token expires', fmtDateTime(data.token_expires_at)],
            ['Connection enabled', data.enabled ? 'Yes' : 'No'],
          ].map(([k, v]) => (
            <div key={k} className="flex items-center justify-between border-b border-white/5 py-2 last:border-0">
              <dt className="text-xs text-slate-500">{k}</dt>
              <dd className="num text-[13px] font-semibold text-slate-200">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <Card
        title="Daily access token"
        icon={KeyRound}
        subtitle="Broker tokens expire every day. Saving one immediately refreshes your candles, zones and base rates in the background."
      >
        <form onSubmit={save} className="space-y-3">
          <Field label="Access token" hint="Stored encrypted at rest; never shown again after saving.">
            <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="Paste today's access token" required minLength={10} />
          </Field>
          {msg && (
            <p className={`rounded-xl px-3 py-2.5 text-[13px] font-medium ring-1 ${msg.ok ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/25' : 'bg-rose-500/10 text-rose-300 ring-rose-500/25'}`}>
              {msg.text}
            </p>
          )}
          <Button type="submit" loading={busy} icon={KeyRound}>
            Save token
          </Button>
        </form>
      </Card>
    </div>
  )
}
