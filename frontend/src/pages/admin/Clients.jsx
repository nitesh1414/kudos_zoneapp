import { useMemo, useState } from 'react'
import {
  CheckCircle2, KeyRound, LayoutGrid, List, Pencil, Plus, PowerOff, Search, Trash2, UserPlus, Users, XCircle,
} from 'lucide-react'
import { api, endpoints } from '../../lib/api.js'
import { useApi, fmtDate } from '../../lib/hooks.js'
import {
  Avatar, Badge, Button, Card, Empty, ErrorState, Field, IconButton, Input, Modal, Select, Skeleton,
  TableWrap, Td, Th,
} from '../../components/ui.jsx'

const emptyForm = { display_name: '', username: '', password: '', symbol: 'NSE:NIFTY50-INDEX', broker_id: '' }

function ClientForm({ mode, form, setForm, brokers, error }) {
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  return (
    <div className="space-y-3.5">
      <Field label="Display name">
        <Input value={form.display_name} onChange={set('display_name')} placeholder="Rahul Kulkarni" required />
      </Field>
      {mode === 'create' && (
        <Field label="Username" hint="Lower-cased automatically. Used to sign in.">
          <Input value={form.username} onChange={set('username')} placeholder="rahul.k" minLength={3} required />
        </Field>
      )}
      <Field label={mode === 'create' ? 'Temporary password' : 'New password'} hint={mode === 'edit' ? 'Leave blank to keep the current password.' : '8 characters minimum.'}>
        <Input type="password" value={form.password} onChange={set('password')} placeholder="••••••••" minLength={8} required={mode === 'create'} />
      </Field>
      <Field label="Market symbol" hint="Exact provider symbol, e.g. NSE:NIFTY50-INDEX.">
        <Input value={form.symbol} onChange={set('symbol')} placeholder="NSE:NIFTY50-INDEX" required />
      </Field>
      <Field label="Broker connection">
        <Select value={form.broker_id ?? ''} onChange={set('broker_id')}>
          <option value="">Not assigned</option>
          {brokers.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </Select>
      </Field>
      {error && <p className="rounded-xl bg-rose-500/10 px-3 py-2.5 text-[13px] text-rose-300 ring-1 ring-rose-500/25">{error}</p>}
    </div>
  )
}

function ClientCard({ c, onEdit, onToggle, onDelete }) {
  return (
    <div className="card animate-rise flex flex-col gap-3 p-4 transition hover:border-brand-500/30">
      <div className="flex items-start gap-3">
        <Avatar name={c.display_name || c.username} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-bold text-slate-100">{c.display_name}</p>
          <p className="truncate text-xs text-slate-500">@{c.username}</p>
        </div>
        <Badge tone={c.active ? 'up' : 'neutral'}>
          {c.active ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
          {c.active ? 'Active' : 'Disabled'}
        </Badge>
      </div>
      <dl className="space-y-1 text-[12.5px]">
        <div className="flex justify-between gap-3 border-b border-white/5 py-1.5">
          <dt className="text-slate-500">Symbol</dt>
          <dd className="num truncate font-semibold text-slate-200">{c.symbol}</dd>
        </div>
        <div className="flex justify-between gap-3 border-b border-white/5 py-1.5">
          <dt className="text-slate-500">Broker</dt>
          <dd className="truncate font-semibold text-slate-200">{c.broker_name || 'Not assigned'}</dd>
        </div>
        <div className="flex justify-between gap-3 py-1.5">
          <dt className="text-slate-500">Created</dt>
          <dd className="num text-slate-300">{fmtDate(c.created_at)}</dd>
        </div>
      </dl>
      <div className="flex gap-2">
        <Button variant="ghost" size="sm" icon={Pencil} className="flex-1" onClick={() => onEdit(c)}>
          Edit
        </Button>
        <Button variant="ghost" size="sm" icon={PowerOff} onClick={() => onToggle(c)} title={c.active ? 'Disable' : 'Enable'}>
          {c.active ? 'Disable' : 'Enable'}
        </Button>
        <IconButton icon={Trash2} tone="danger" label="Delete client" onClick={() => onDelete(c)} />
      </div>
    </div>
  )
}

export default function Clients() {
  const clients = useApi(endpoints.clients)
  const brokers = useApi(endpoints.brokers)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [view, setView] = useState('grid')
  const [modal, setModal] = useState(null) // {mode:'create'|'edit', client}
  const [confirm, setConfirm] = useState(null)
  const [form, setForm] = useState(emptyForm)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const rows = useMemo(() => {
    const list = clients.data || []
    const q = query.trim().toLowerCase()
    return list.filter(
      (c) =>
        (status === 'all' || (status === 'active' ? c.active : !c.active)) &&
        (!q ||
          [c.display_name, c.username, c.symbol, c.broker_name].some((v) => String(v || '').toLowerCase().includes(q))),
    )
  }, [clients.data, query, status])

  const openCreate = () => {
    setForm(emptyForm)
    setError('')
    setModal({ mode: 'create' })
  }
  const openEdit = (c) => {
    setForm({
      display_name: c.display_name || '',
      username: c.username,
      password: '',
      symbol: c.symbol || '',
      broker_id: c.broker_id ?? '',
    })
    setError('')
    setModal({ mode: 'edit', client: c })
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const brokerId = form.broker_id === '' ? null : Number(form.broker_id)
      if (modal.mode === 'create') {
        await api.post(endpoints.clients, {
          username: form.username.trim().toLowerCase(),
          display_name: form.display_name.trim(),
          password: form.password,
          symbol: form.symbol.trim(),
          broker_id: brokerId,
        })
      } else {
        const body = { display_name: form.display_name.trim(), symbol: form.symbol.trim(), broker_id: brokerId }
        if (form.password) body.password = form.password
        await api.patch(endpoints.client(modal.client.id), body)
      }
      setModal(null)
      clients.reload()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (c) => {
    await api.patch(endpoints.client(c.id), { active: !c.active })
    clients.reload()
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api.del(endpoints.client(confirm.id))
      setConfirm(null)
      clients.reload()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const all = clients.data || []
  const stats = [
    { label: 'Total clients', value: all.length, icon: Users, tone: 'text-brand-400 bg-brand-500/10' },
    { label: 'Active', value: all.filter((c) => c.active).length, icon: CheckCircle2, tone: 'text-emerald-400 bg-emerald-500/10' },
    { label: 'Without broker', value: all.filter((c) => !c.broker_id).length, icon: KeyRound, tone: 'text-amber-400 bg-amber-500/10' },
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

      <Card
        title="Client management"
        icon={Users}
        subtitle="Separate logins, assigned symbols and broker connections."
        right={
          <Button icon={UserPlus} onClick={openCreate}>
            <span className="hidden sm:inline">Add client</span>
            <span className="sm:hidden">Add</span>
          </Button>
        }
      >
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1">
            <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-500" />
            <Input className="pl-9" placeholder="Search name, username, symbol…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <Select className="w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">All statuses</option>
            <option value="active">Active only</option>
            <option value="disabled">Disabled only</option>
          </Select>
          <div className="flex rounded-xl bg-white/5 p-1 ring-1 ring-white/10">
            {[
              ['grid', LayoutGrid],
              ['table', List],
            ].map(([key, Icon]) => (
              <button
                key={key}
                onClick={() => setView(key)}
                className={`grid size-8 place-items-center rounded-lg transition ${view === key ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                aria-label={`${key} view`}
              >
                <Icon size={15} />
              </button>
            ))}
          </div>
        </div>

        {clients.loading && <Skeleton className="h-48" />}
        {clients.error && <ErrorState error={clients.error} onRetry={clients.reload} />}
        {clients.data && rows.length === 0 && (
          <Empty
            icon={Users}
            title={all.length === 0 ? 'No clients yet' : 'No matching clients'}
            hint={all.length === 0 ? 'Create the first client login and assign a broker connection.' : 'Try a different search or filter.'}
            action={all.length === 0 && <Button icon={Plus} onClick={openCreate}>Add client</Button>}
          />
        )}

        {rows.length > 0 && view === 'grid' && (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {rows.map((c) => (
              <ClientCard key={c.id} c={c} onEdit={openEdit} onToggle={toggle} onDelete={setConfirm} />
            ))}
          </div>
        )}

        {rows.length > 0 && view === 'table' && (
          <TableWrap>
            <thead>
              <tr>
                <Th>Client</Th>
                <Th>Symbol</Th>
                <Th>Broker</Th>
                <Th>Created</Th>
                <Th>Status</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="transition hover:bg-white/3">
                  <Td>
                    <div className="flex items-center gap-3">
                      <Avatar name={c.display_name || c.username} size="sm" />
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-slate-100">{c.display_name}</p>
                        <p className="truncate text-xs text-slate-500">@{c.username}</p>
                      </div>
                    </div>
                  </Td>
                  <Td className="num text-xs">{c.symbol}</Td>
                  <Td className="text-xs">{c.broker_name || <span className="text-slate-500">Not assigned</span>}</Td>
                  <Td className="num text-xs text-slate-400">{fmtDate(c.created_at)}</Td>
                  <Td>
                    <Badge tone={c.active ? 'up' : 'neutral'}>{c.active ? 'Active' : 'Disabled'}</Badge>
                  </Td>
                  <Td>
                    <div className="flex justify-end gap-1.5">
                      <IconButton icon={Pencil} label="Edit client" onClick={() => openEdit(c)} />
                      <IconButton icon={PowerOff} label={c.active ? 'Disable' : 'Enable'} onClick={() => toggle(c)} />
                      <IconButton icon={Trash2} tone="danger" label="Delete client" onClick={() => setConfirm(c)} />
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <Modal
        open={!!modal}
        onClose={() => setModal(null)}
        icon={modal?.mode === 'edit' ? Pencil : UserPlus}
        title={modal?.mode === 'edit' ? `Edit ${modal.client.display_name}` : 'Add client'}
        subtitle={modal?.mode === 'edit' ? `@${modal.client.username}` : 'Creates a separate client login.'}
        footer={
          <>
            <Button variant="ghost" onClick={() => setModal(null)}>
              Cancel
            </Button>
            <Button form="client-form" type="submit" loading={busy}>
              {modal?.mode === 'edit' ? 'Save changes' : 'Create client'}
            </Button>
          </>
        }
      >
        <form id="client-form" onSubmit={submit}>
          <ClientForm mode={modal?.mode} form={form} setForm={setForm} brokers={brokers.data || []} error={error} />
        </form>
      </Modal>

      <Modal
        open={!!confirm}
        onClose={() => setConfirm(null)}
        icon={Trash2}
        title="Delete client"
        subtitle="This removes the login, its sessions and broker assignment."
        width="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={remove} icon={Trash2}>
              Delete permanently
            </Button>
          </>
        }
      >
        {confirm && (
          <div className="flex items-center gap-3.5">
            <Avatar name={confirm.display_name || confirm.username} size="lg" />
            <div>
              <p className="font-semibold text-slate-100">{confirm.display_name}</p>
              <p className="text-xs text-slate-500">@{confirm.username}</p>
            </div>
          </div>
        )}
        <p className="mt-4 text-[13px] leading-relaxed text-slate-400">
          Stored market data is not affected. This action cannot be undone.
        </p>
      </Modal>
    </div>
  )
}
