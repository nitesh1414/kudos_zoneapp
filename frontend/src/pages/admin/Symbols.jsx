import { useMemo, useState } from 'react'
import {
  CandlestickChart, CheckCircle2, DatabaseZap, Layers, PlayCircle, Plus, Power, Search, Star, Tags, Trash2,
} from 'lucide-react'
import { api, endpoints } from '../../lib/api.js'
import { useApi, fmtDate, fmtNum } from '../../lib/hooks.js'
import { useSymbol } from '../../lib/symbol.jsx'
import {
  Badge, Button, Card, Empty, ErrorState, Field, IconButton, Input, Modal, Select, Skeleton,
  TableWrap, Td, Th,
} from '../../components/ui.jsx'

export default function Symbols() {
  const symbols = useApi(endpoints.symbols)
  const brokers = useApi(endpoints.brokers)
  const { refreshTracked, aliases, resolutions: catalogResolutions, defaultSymbol } = useSymbol()
  // Everything below is database-driven: aliases teach the shortcuts, the
  // provider tells us which timeframes exist.
  const RESOLUTIONS = catalogResolutions.length ? catalogResolutions : ['15', 'D']
  const QUICK_ADD = [...new Set(Object.entries(aliases)
    .filter(([alias]) => !alias.includes(' '))
    .map(([alias]) => alias))].slice(0, 8)
  const [query, setQuery] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState({ symbol: '', label: '', broker_id: '', resolutions: ['15', 'D'], seed_days: 180 })
  const [aliasForm, setAliasForm] = useState({ alias: '', symbol: '' })
  const [confirm, setConfirm] = useState(null)
  const [purge, setPurge] = useState(false)
  const [seedDays, setSeedDays] = useState(180)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (symbols.data || []).filter(
      (r) => !q || [r.symbol, r.label, r.broker_name].some((v) => String(v || '').toLowerCase().includes(q)),
    )
  }, [symbols.data, query])

  const reload = () => {
    symbols.reload()
    refreshTracked?.()
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    try {
      const res = await api.post(endpoints.adminSymbols, {
        symbol: form.symbol,
        label: form.label,
        resolutions: form.resolutions,
        broker_id: form.broker_id === '' ? null : Number(form.broker_id),
        seed: true,
        seed_days: Number(form.seed_days),
      })
      setMsg({ ok: true, text: res.seed_message })
      setAddOpen(false)
      setForm({ ...form, symbol: '', label: '' })
      reload()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const quickAdd = async (symbol) => {
    setMsg({ ok: true, text: `Adding ${symbol}…` })
    try {
      const res = await api.post(endpoints.adminSymbols, { symbol, seed: true, seed_days: seedDays })
      setMsg({ ok: true, text: res.seed_message })
      reload()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  const makeDefault = async (row) => {
    await api.patch(endpoints.adminSymbol(row.symbol), { is_default: true })
    setMsg({ ok: true, text: `${row.symbol} is now the symbol everyone lands on.` })
    reload()
  }

  const addAlias = async (e) => {
    e.preventDefault()
    setMsg(null)
    try {
      await api.post(endpoints.symbolAliases, aliasForm)
      setMsg({ ok: true, text: `Typing "${aliasForm.alias}" now means ${aliasForm.symbol}.` })
      setAliasForm({ alias: '', symbol: '' })
      reload()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  const toggle = async (row) => {
    await api.patch(endpoints.adminSymbol(row.symbol), { active: !row.active })
    reload()
  }

  const seedOne = async (row) => {
    setMsg({ ok: true, text: `Starting a ${seedDays}-day fetch for ${row.symbol}…` })
    try {
      const res = await api.post(endpoints.symbolSeed(row.symbol), { days: seedDays })
      setMsg({ ok: true, text: res.seed_message })
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  const seedEverything = async () => {
    setBusy(true)
    setMsg({ ok: true, text: 'Starting a fetch for every tracked symbol…' })
    try {
      const res = await api.post(endpoints.seedAll, { days: seedDays })
      setMsg({ ok: true, text: res.seed_message })
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api.del(`${endpoints.adminSymbol(confirm.symbol)}?purge=${purge}`)
      setConfirm(null)
      setPurge(false)
      reload()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const all = symbols.data || []
  const stats = [
    { label: 'Tracked symbols', value: all.length, icon: Layers, tone: 'text-brand-400 bg-brand-500/10' },
    { label: 'Active', value: all.filter((r) => r.active).length, icon: CheckCircle2, tone: 'text-emerald-400 bg-emerald-500/10' },
    { label: 'Awaiting data', value: all.filter((r) => !Number(r.bars)).length, icon: DatabaseZap, tone: 'text-amber-400 bg-amber-500/10' },
  ]

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        {stats.map(({ label, value, icon: Icon, tone }) => (
          <div key={label} className="card animate-rise flex items-center gap-3.5 px-4 py-3.5">
            <div className={`grid size-10 place-items-center rounded-xl ${tone}`}>
              <Icon size={18} />
            </div>
            <div>
              <p className="text-[11px] tracking-wider text-slate-500 uppercase">{label}</p>
              <p className="num text-xl font-bold text-slate-50">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {msg && (
        <div className={`card animate-rise px-4 py-3 text-[13px] ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`}>
          {msg.text}
        </div>
      )}

      <Card
        title="Market symbols"
        icon={CandlestickChart}
        subtitle="Every symbol here is fetched and run through the zone engine — whether or not a client is assigned to it."
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Select className="w-32 py-1.5 text-xs" value={seedDays} onChange={(e) => setSeedDays(Number(e.target.value))}>
              {[30, 90, 180, 365, 730].map((d) => (
                <option key={d} value={d}>
                  {d} days
                </option>
              ))}
            </Select>
            <Button variant="ghost" size="sm" icon={PlayCircle} loading={busy} onClick={seedEverything}>
              <span className="hidden sm:inline">Fetch all</span>
            </Button>
            <Button size="sm" icon={Plus} onClick={() => setAddOpen(true)}>
              <span className="hidden sm:inline">Add symbol</span>
              <span className="sm:hidden">Add</span>
            </Button>
          </div>
        }
      >
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1">
            <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-500" />
            <Input className="pl-9" placeholder="Search symbol or label…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_ADD.map((s) => (
              <button
                key={s}
                onClick={() => quickAdd(s)}
                className="rounded-full bg-white/5 px-3 py-1.5 text-[11px] font-semibold text-slate-300 ring-1 ring-white/10 transition hover:bg-brand-500/20 hover:text-white"
              >
                + {s}
              </button>
            ))}
          </div>
        </div>

        {symbols.loading && <Skeleton className="h-40" />}
        {symbols.error && <ErrorState error={symbols.error} onRetry={symbols.reload} />}
        {symbols.data && rows.length === 0 && (
          <Empty
            icon={CandlestickChart}
            title={all.length === 0 ? 'No symbols tracked yet' : 'No matching symbols'}
            hint={all.length === 0 ? 'Add NIFTY, BANKNIFTY or any exact provider symbol to start collecting data for it.' : 'Try a different search.'}
            action={all.length === 0 && <Button icon={Plus} onClick={() => setAddOpen(true)}>Add symbol</Button>}
          />
        )}

        {rows.length > 0 && (
          <TableWrap>
            <thead>
              <tr>
                <Th>Symbol</Th>
                <Th>Timeframes</Th>
                <Th>Broker</Th>
                <Th>Bars</Th>
                <Th>Sessions</Th>
                <Th>Last candle</Th>
                <Th>Clients</Th>
                <Th>Status</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} className="transition hover:bg-white/3">
                  <Td>
                    <div className="flex items-center gap-3">
                      <div className="grid size-9 place-items-center rounded-xl bg-brand-500/12 text-brand-400">
                        <CandlestickChart size={16} />
                      </div>
                      <div className="min-w-0">
                        <p className="num truncate text-[13px] font-semibold text-slate-100">{r.symbol}</p>
                        {r.label && <p className="truncate text-xs text-slate-500">{r.label}</p>}
                      </div>
                    </div>
                  </Td>
                  <Td className="num text-xs text-slate-400">{(r.resolutions || []).join(', ')}</Td>
                  <Td className="text-xs">{r.broker_name || <span className="text-slate-500">Any enabled</span>}</Td>
                  <Td className="num text-slate-200">{fmtNum(r.bars)}</Td>
                  <Td className="num text-slate-200">{fmtNum(r.sessions)}</Td>
                  <Td className="num text-xs text-slate-400">{r.last_bar_date ? fmtDate(r.last_bar_date) : '—'}</Td>
                  <Td className="num text-xs text-slate-400">{fmtNum(r.clients)}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1.5">
                      <Badge tone={r.active ? 'up' : 'neutral'}>{r.active ? 'Tracking' : 'Paused'}</Badge>
                      {r.is_default && <Badge tone="brand">Default</Badge>}
                    </div>
                  </Td>
                  <Td>
                    <div className="flex justify-end gap-1.5">
                      <IconButton icon={Star} label={r.is_default ? 'Landing symbol' : 'Make the landing symbol'}
                                  onClick={() => makeDefault(r)} tone={r.is_default ? 'ghost' : 'ghost'} />
                      <IconButton icon={DatabaseZap} label="Fetch data now" onClick={() => seedOne(r)} />
                      <IconButton icon={Power} label={r.active ? 'Pause tracking' : 'Resume tracking'} onClick={() => toggle(r)} />
                      <IconButton icon={Trash2} tone="danger" label="Remove symbol" onClick={() => setConfirm(r)} />
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <Card title="Symbol shortcuts" icon={Tags}
            subtitle="Aliases are stored in the database: type the shorthand anywhere and it expands to the provider symbol.">
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(aliases).map(([alias, target]) => (
            <span key={alias} className="rounded-full bg-white/5 px-3 py-1.5 text-[11.5px] text-slate-300 ring-1 ring-white/10">
              <b className="text-slate-100">{alias}</b> <span className="text-slate-500">→</span>{' '}
              <span className="num">{target}</span>
            </span>
          ))}
        </div>
        <form onSubmit={addAlias} className="mt-4 flex flex-col gap-2 sm:flex-row">
          <Input value={aliasForm.alias} onChange={(e) => setAliasForm({ ...aliasForm, alias: e.target.value })}
                 placeholder="Shortcut, e.g. SENSEX" className="sm:w-56" required />
          <Input value={aliasForm.symbol} onChange={(e) => setAliasForm({ ...aliasForm, symbol: e.target.value })}
                 placeholder="Provider symbol, e.g. BSE:SENSEX-INDEX" className="flex-1" required />
          <Button type="submit" icon={Plus}>Add shortcut</Button>
        </form>
      </Card>

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        icon={Plus}
        title="Add symbol"
        subtitle="Aliases like NIFTY or BANKNIFTY are expanded automatically."
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button form="symbol-form" type="submit" loading={busy}>
              Add & fetch
            </Button>
          </>
        }
      >
        <form id="symbol-form" onSubmit={submit} className="space-y-3.5">
          <Field label="Symbol" hint="NIFTY, BANKNIFTY, NSE:RELIANCE-EQ, MCX:CRUDEOIL25AUGFUT …">
            <Input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} placeholder="NSE:NIFTY50-INDEX" required />
          </Field>
          <Field label="Label (optional)">
            <Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="Nifty 50" />
          </Field>
          <Field label="Timeframes" hint="15-minute is always included — the zone engine needs it.">
            <div className="flex flex-wrap gap-1.5">
              {RESOLUTIONS.map((r) => {
                const on = form.resolutions.includes(r)
                return (
                  <button
                    key={r}
                    type="button"
                    onClick={() =>
                      setForm({
                        ...form,
                        resolutions: on ? form.resolutions.filter((x) => x !== r) : [...form.resolutions, r],
                      })
                    }
                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold ring-1 transition ${
                      on ? 'bg-brand-600 text-white ring-brand-500' : 'bg-white/5 text-slate-300 ring-white/10'
                    }`}
                  >
                    {r === 'D' ? 'Daily' : `${r}m`}
                  </button>
                )
              })}
            </div>
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Broker connection">
              <Select value={form.broker_id} onChange={(e) => setForm({ ...form, broker_id: e.target.value })}>
                <option value="">Any enabled connection</option>
                {(brokers.data || []).map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="History to fetch">
              <Select value={form.seed_days} onChange={(e) => setForm({ ...form, seed_days: e.target.value })}>
                {[30, 90, 180, 365, 730].map((d) => (
                  <option key={d} value={d}>
                    Last {d} days
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!confirm}
        onClose={() => setConfirm(null)}
        icon={Trash2}
        title="Stop tracking symbol"
        subtitle={confirm?.symbol}
        width="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={remove} icon={Trash2}>
              Remove
            </Button>
          </>
        }
      >
        <p className="text-[13px] leading-relaxed text-slate-400">
          The symbol stops being fetched. Clients assigned to it keep their assignment and its stored history is
          retained unless you clear it below.
        </p>
        <label className="mt-3 flex items-start gap-2.5 rounded-xl bg-white/4 px-3.5 py-3 ring-1 ring-white/8">
          <input type="checkbox" checked={purge} onChange={(e) => setPurge(e.target.checked)} className="mt-0.5 size-4 accent-rose-500" />
          <span className="text-[12.5px] text-slate-300">
            Also delete stored candles, zone sheets and outcomes for this symbol
            {confirm ? ` (${fmtNum(confirm.bars)} bars)` : ''}.
          </span>
        </label>
      </Modal>
    </div>
  )
}
