import { useState } from 'react'
import { CalendarDays, Plus, Trash2 } from 'lucide-react'
import { api, endpoints } from '../../lib/api.js'
import { useApi, fmtDate } from '../../lib/hooks.js'
import { Button, Card, Empty, ErrorState, Field, IconButton, Input, Skeleton, TableWrap, Td, Th } from '../../components/ui.jsx'

export default function Holidays() {
  const { data, error, loading, reload } = useApi(endpoints.holidays)
  const [form, setForm] = useState({ holiday_date: '', label: 'Market holiday' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    setMsg('')
    try {
      await api.post(endpoints.holidays, form)
      setForm({ holiday_date: '', label: 'Market holiday' })
      reload()
    } catch (err) {
      setMsg(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (d) => {
    await api.del(endpoints.holiday(d))
    reload()
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr]">
      <Card title="Add holiday" icon={Plus} subtitle="The market-close job skips these dates.">
        <form onSubmit={add} className="space-y-3.5">
          <Field label="Date">
            <Input type="date" value={form.holiday_date} onChange={(e) => setForm({ ...form, holiday_date: e.target.value })} required />
          </Field>
          <Field label="Label">
            <Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} required />
          </Field>
          {msg && <p className="rounded-xl bg-rose-500/10 px-3 py-2.5 text-[13px] text-rose-300 ring-1 ring-rose-500/25">{msg}</p>}
          <Button type="submit" loading={busy} icon={Plus}>
            Add holiday
          </Button>
        </form>
      </Card>

      <Card title="Market holidays" icon={CalendarDays}>
        {loading && <Skeleton className="h-40" />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && data.length === 0 && <Empty icon={CalendarDays} title="No holidays configured" hint="Weekends are skipped automatically." />}
        {data && data.length > 0 && (
          <TableWrap>
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Label</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {data.map((h) => (
                <tr key={h.holiday_date} className="transition hover:bg-white/3">
                  <Td className="num font-semibold whitespace-nowrap">{fmtDate(h.holiday_date)}</Td>
                  <Td className="text-slate-300">{h.label}</Td>
                  <Td>
                    <div className="flex justify-end">
                      <IconButton icon={Trash2} tone="danger" label="Remove holiday" onClick={() => remove(String(h.holiday_date).slice(0, 10))} />
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
    </div>
  )
}
