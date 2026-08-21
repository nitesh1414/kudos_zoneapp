import { useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2, CloudDownload, KeyRound, Link2, Plug, Plus, RefreshCw, Trash2, TriangleAlert,
} from 'lucide-react'
import { api, endpoints } from '../../lib/api.js'
import { useApi, fmtDateTime } from '../../lib/hooks.js'
import {
  Badge, Button, Card, Empty, ErrorState, Field, IconButton, Input, Modal, Skeleton, TableWrap, Td, Th,
} from '../../components/ui.jsx'

const tokenTone = { valid: 'up', expiring: 'warn', expired: 'down', unknown: 'neutral' }

export default function Brokers() {
  const brokers = useApi(endpoints.brokers)
  const types = useApi(endpoints.brokerTypes)
  const [addOpen, setAddOpen] = useState(false)
  const [typeKey, setTypeKey] = useState('')
  const [creds, setCreds] = useState({})
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [tokenFor, setTokenFor] = useState(null)
  const [tokenValue, setTokenValue] = useState('')
  const [backfillFor, setBackfillFor] = useState(null)
  const [backfill, setBackfill] = useState({ symbol: 'NSE:NIFTY50-INDEX', date_from: '2015-01-01', date_to: '' })
  const [confirm, setConfirm] = useState(null)
  const [result, setResult] = useState(null)
  const [authUrl, setAuthUrl] = useState('')
  const [authCode, setAuthCode] = useState('')

  const spec = useMemo(() => (types.data || []).find((t) => t.key === typeKey), [types.data, typeKey])

  useEffect(() => {
    if (!typeKey && types.data?.length) setTypeKey(types.data[0].key)
  }, [types.data, typeKey])

  useEffect(() => {
    setCreds(spec?.defaults ? { ...spec.defaults } : {})
  }, [spec])

  const create = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.post(endpoints.brokers, { name: name.trim(), broker_type: typeKey, credentials: creds, enabled: true })
      setAddOpen(false)
      setName('')
      brokers.reload()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const generateUrl = async () => {
    setError('')
    try {
      const res = await api.get(endpoints.fyersUrl)
      setAuthUrl(res.url)
    } catch (err) {
      setError(err.message)
    }
  }

  const exchange = async () => {
    setError('')
    try {
      const code = authCode.includes('auth_code=')
        ? new URL(authCode).searchParams.get('auth_code')
        : authCode.trim()
      const res = await api.post(endpoints.fyersExchange, { auth_code: code })
      setCreds((c) => ({ ...c, access_token: res.access_token }))
      setTokenValue(res.access_token)
    } catch (err) {
      setError(err.message)
    }
  }

  const saveToken = async () => {
    setBusy(true)
    setResult(null)
    try {
      const res = await api.post(endpoints.brokerToken(tokenFor.id), { access_token: tokenValue.trim() })
      setResult({ ok: true, text: res.message || 'Token saved.' })
      setTokenFor(null)
      setTokenValue('')
      brokers.reload()
    } catch (err) {
      setResult({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const runBackfill = async () => {
    setBusy(true)
    setResult(null)
    try {
      const body = { symbol: backfill.symbol.trim(), date_from: backfill.date_from }
      if (backfill.date_to) body.date_to = backfill.date_to
      const res = await api.post(endpoints.brokerBackfill(backfillFor.id), body)
      setResult({ ok: true, text: `Backfill finished: ${JSON.stringify(res.by_resolution || res)}` })
      setBackfillFor(null)
    } catch (err) {
      setResult({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const test = async (b) => {
    setResult({ ok: true, text: `Testing ${b.name}…` })
    try {
      const res = await api.post(endpoints.brokerTest(b.id))
      setResult({ ok: res.connected, text: `${b.name}: ${res.message}` })
    } catch (err) {
      setResult({ ok: false, text: err.message })
    }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api.del(endpoints.broker(confirm.id))
      setConfirm(null)
      brokers.reload()
    } finally {
      setBusy(false)
    }
  }

  const rows = brokers.data || []

  return (
    <div className="space-y-4">
      {result && (
        <div
          className={`card animate-rise flex items-start gap-2.5 px-4 py-3 text-[13px] ${result.ok ? 'text-emerald-300' : 'text-rose-300'}`}
        >
          {result.ok ? <CheckCircle2 size={16} className="mt-0.5" /> : <TriangleAlert size={16} className="mt-0.5" />}
          <span className="break-words">{result.text}</span>
        </div>
      )}

      <Card
        title="Broker connections"
        icon={Plug}
        subtitle="Credentials are encrypted at rest. Tokens expire daily and must be refreshed."
        right={
          <Button icon={Plus} onClick={() => setAddOpen(true)}>
            <span className="hidden sm:inline">Add broker</span>
            <span className="sm:hidden">Add</span>
          </Button>
        }
      >
        {brokers.loading && <Skeleton className="h-40" />}
        {brokers.error && <ErrorState error={brokers.error} onRetry={brokers.reload} />}
        {brokers.data && rows.length === 0 && (
          <Empty icon={Plug} title="No broker connections" hint="Add a provider connection, then assign it to your clients." />
        )}
        {rows.length > 0 && (
          <TableWrap>
            <thead>
              <tr>
                <Th>Connection</Th>
                <Th>Provider</Th>
                <Th>Timeframes</Th>
                <Th>Token</Th>
                <Th>Expires</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id} className="transition hover:bg-white/3">
                  <Td>
                    <div className="flex items-center gap-3">
                      <div className="grid size-9 place-items-center rounded-xl bg-brand-500/12 text-brand-400">
                        <Plug size={16} />
                      </div>
                      <div>
                        <p className="font-semibold text-slate-100">{b.name}</p>
                        <p className="text-xs text-slate-500">{b.enabled ? 'Enabled' : 'Disabled'}</p>
                      </div>
                    </div>
                  </Td>
                  <Td className="text-xs capitalize">{b.broker_type}</Td>
                  <Td className="num text-xs text-slate-400">{(b.resolutions || []).join(', ')}</Td>
                  <Td>
                    <Badge tone={tokenTone[b.token_status] || 'neutral'}>{b.token_status}</Badge>
                  </Td>
                  <Td className="num text-xs text-slate-400">{fmtDateTime(b.token_expires_at)}</Td>
                  <Td>
                    <div className="flex flex-wrap justify-end gap-1.5">
                      <IconButton icon={KeyRound} label="Update daily token" onClick={() => { setTokenFor(b); setTokenValue('') }} />
                      <IconButton icon={CloudDownload} label="Backfill candles" onClick={() => setBackfillFor(b)} />
                      <IconButton icon={RefreshCw} label="Test connection" onClick={() => test(b)} />
                      <IconButton icon={Trash2} tone="danger" label="Delete connection" onClick={() => setConfirm(b)} />
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      {/* Add broker */}
      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        icon={Plug}
        title="Add broker connection"
        subtitle="All supported Indian-market timeframes are enabled; 15-minute is mandatory."
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button form="broker-form" type="submit" loading={busy}>
              Save connection
            </Button>
          </>
        }
      >
        <form id="broker-form" onSubmit={create} className="space-y-3.5">
          <Field label="Connection name">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Main Fyers account" required />
          </Field>
          <Field label="Provider">
            <select
              className="w-full rounded-xl border border-white/10 bg-ink-900/80 px-3 py-2.5 text-sm text-slate-100"
              value={typeKey}
              onChange={(e) => setTypeKey(e.target.value)}
            >
              {(types.data || []).map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          {(spec?.fields || []).map((f) => (
            <Field key={f.name} label={f.label} hint={f.name === 'access_token' ? 'Optional — can be added later.' : undefined}>
              <Input
                type={f.secret && f.name !== 'access_token' ? 'password' : 'text'}
                value={creds[f.name] || ''}
                onChange={(e) => setCreds({ ...creds, [f.name]: e.target.value })}
                required={f.required !== false && f.name !== 'access_token'}
              />
            </Field>
          ))}
          {typeKey === 'fyers' && (
            <div className="rounded-xl border border-white/10 bg-white/3 p-3.5">
              <p className="mb-2.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Token helper</p>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="ghost" size="sm" icon={Link2} onClick={generateUrl}>
                  Generate login URL
                </Button>
                {authUrl && (
                  <a href={authUrl} target="_blank" rel="noreferrer">
                    <Button type="button" size="sm">
                      Open Fyers login
                    </Button>
                  </a>
                )}
              </div>
              {authUrl && (
                <div className="mt-3 space-y-2">
                  <Input value={authUrl} readOnly onClick={(e) => e.target.select()} className="text-[11px]" />
                  <Input
                    value={authCode}
                    onChange={(e) => setAuthCode(e.target.value)}
                    placeholder="Paste the redirect URL or auth_code"
                  />
                  <Button type="button" variant="ghost" size="sm" onClick={exchange}>
                    Exchange for access token
                  </Button>
                </div>
              )}
            </div>
          )}
          {error && <p className="rounded-xl bg-rose-500/10 px-3 py-2.5 text-[13px] text-rose-300 ring-1 ring-rose-500/25">{error}</p>}
        </form>
      </Modal>

      {/* Daily token */}
      <Modal
        open={!!tokenFor}
        onClose={() => setTokenFor(null)}
        icon={KeyRound}
        title="Daily access token"
        subtitle={tokenFor?.name}
        width="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setTokenFor(null)}>
              Cancel
            </Button>
            <Button loading={busy} onClick={saveToken}>
              Save token
            </Button>
          </>
        }
      >
        <Field label="Access token" hint="Verified against the provider before it is stored.">
          <Input value={tokenValue} onChange={(e) => setTokenValue(e.target.value)} placeholder="Paste today's token" />
        </Field>
      </Modal>

      {/* Backfill */}
      <Modal
        open={!!backfillFor}
        onClose={() => setBackfillFor(null)}
        icon={CloudDownload}
        title="Backfill candles"
        subtitle={backfillFor?.name}
        width="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setBackfillFor(null)}>
              Cancel
            </Button>
            <Button loading={busy} onClick={runBackfill}>
              Start backfill
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <Field label="Symbol">
            <Input value={backfill.symbol} onChange={(e) => setBackfill({ ...backfill, symbol: e.target.value })} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="From">
              <Input type="date" value={backfill.date_from} onChange={(e) => setBackfill({ ...backfill, date_from: e.target.value })} />
            </Field>
            <Field label="To" hint="Blank = today">
              <Input type="date" value={backfill.date_to} onChange={(e) => setBackfill({ ...backfill, date_to: e.target.value })} />
            </Field>
          </div>
          <p className="text-[12px] leading-relaxed text-slate-500">
            Long ranges can take several minutes. Zone results are rebuilt when 15-minute candles are included.
          </p>
        </div>
      </Modal>

      {/* Delete */}
      <Modal
        open={!!confirm}
        onClose={() => setConfirm(null)}
        icon={Trash2}
        title="Delete broker connection"
        subtitle={confirm?.name}
        width="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={remove}>
              Delete
            </Button>
          </>
        }
      >
        <p className="text-[13px] leading-relaxed text-slate-400">
          Clients assigned to this connection will lose their data source until another one is assigned.
        </p>
      </Modal>
    </div>
  )
}
