import { useState } from 'react'
import { Activity, PlayCircle, Save, Zap } from 'lucide-react'
import { api, endpoints } from '../../lib/api.js'
import { useApi } from '../../lib/hooks.js'
import { Button, Card, Field, Input, Skeleton } from '../../components/ui.jsx'

function GiftNifty() {
  const { data, loading, reload } = useApi(endpoints.giftNifty)
  const [form, setForm] = useState({ ltp: '', pdc: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const save = async (e) => {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    try {
      await api.put(endpoints.giftNifty, { ltp: Number(form.ltp), pdc: Number(form.pdc) })
      setMsg({ ok: true, text: 'Snapshot published to every dashboard.' })
      reload()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="GIFT Nifty snapshot" icon={Activity} subtitle="Shown on the Overview tab for all clients.">
      {loading ? (
        <Skeleton className="h-24" />
      ) : (
        <form onSubmit={save} className="space-y-3.5">
          {data?.ltp && (
            <p className="num rounded-xl bg-white/4 px-3 py-2.5 text-[13px] text-slate-300 ring-1 ring-white/8">
              Current: {data.ltp} vs PDC {data.pdc} · gap {data.gap_pct}%
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Last traded price">
              <Input type="number" step="0.05" value={form.ltp} onChange={(e) => setForm({ ...form, ltp: e.target.value })} required />
            </Field>
            <Field label="Previous close">
              <Input type="number" step="0.05" value={form.pdc} onChange={(e) => setForm({ ...form, pdc: e.target.value })} required />
            </Field>
          </div>
          {msg && (
            <p className={`rounded-xl px-3 py-2.5 text-[13px] ring-1 ${msg.ok ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/25' : 'bg-rose-500/10 text-rose-300 ring-rose-500/25'}`}>
              {msg.text}
            </p>
          )}
          <Button type="submit" loading={busy} icon={Save}>
            Publish snapshot
          </Button>
        </form>
      )}
    </Card>
  )
}

export default function Jobs() {
  const [output, setOutput] = useState('No manual run started.')
  const [busy, setBusy] = useState(false)

  const run = async (force) => {
    setBusy(true)
    setOutput(force ? 'Forcing market-close run…' : 'Running market-close job…')
    try {
      const res = await api.post(endpoints.marketClose(force))
      setOutput(JSON.stringify(res, null, 2))
    } catch (err) {
      setOutput(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card
        title="Market-close calculation"
        icon={PlayCircle}
        subtitle="Runs automatically at 5:00 PM Asia/Kolkata on trading weekdays. Weekends and configured holidays are skipped."
      >
        <div className="flex flex-wrap gap-2">
          <Button icon={PlayCircle} loading={busy} onClick={() => run(false)}>
            Run now
          </Button>
          <Button variant="ghost" icon={Zap} disabled={busy} onClick={() => run(true)}>
            Force run
          </Button>
        </div>
        <pre className="scrollbar-thin mt-4 max-h-80 overflow-auto rounded-xl border border-white/10 bg-ink-950/80 p-3.5 text-[12px] leading-relaxed whitespace-pre-wrap text-slate-300">
          {output}
        </pre>
      </Card>
      <GiftNifty />
    </div>
  )
}
