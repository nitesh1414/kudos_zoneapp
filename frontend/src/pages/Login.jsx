import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { BarChart3, Eye, EyeOff, Layers, Lock, ShieldCheck, TrendingUp, User } from 'lucide-react'
import { useAuth } from '../lib/auth.jsx'
import { Button, Input } from '../components/ui.jsx'

const HIGHLIGHTS = [
  { icon: Layers, title: 'Next-session zones', text: 'Pivot, CPR and round-number clusters ranked by empirical weight.' },
  { icon: BarChart3, title: 'Honest base rates', text: 'Touch, hold and gap-fill rates measured on your stored sample.' },
  { icon: ShieldCheck, title: 'Per-client access', text: 'Separate logins, assigned symbols and encrypted broker credentials.' },
]

export default function Login() {
  const { user, loading, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!loading && user) return <Navigate to="/dashboard/overview" replace />

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(err.message || 'Sign in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative z-10 grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* Brand / marketing side */}
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-white/8 p-10 lg:flex xl:p-14">
        <div className="flex items-center gap-3">
          <div className="grid size-11 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-violet-600 text-white shadow-xl shadow-brand-600/30">
            <Layers size={22} />
          </div>
          <div>
            <div className="text-lg font-extrabold tracking-tight text-white">
              Zone<span className="text-brand-400">App</span>
            </div>
            <div className="text-[11px] tracking-wider text-slate-500 uppercase">Market structure workspace</div>
          </div>
        </div>

        <div className="max-w-lg">
          <h1 className="text-4xl leading-[1.1] font-extrabold tracking-tight text-white xl:text-[42px]">
            Next-session support & resistance,
            <span className="bg-gradient-to-r from-brand-400 to-emerald-400 bg-clip-text text-transparent"> with the receipts.</span>
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-slate-400">
            Every zone carries the historical base rate behind it, so you always see how often a level was actually
            reached and held — never a forecast, never a tip.
          </p>
          <div className="mt-9 space-y-4">
            {HIGHLIGHTS.map(({ icon: Icon, title, text }) => (
              <div key={title} className="flex gap-3.5">
                <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-white/5 text-brand-400 ring-1 ring-white/10">
                  <Icon size={18} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-100">{title}</p>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-slate-500">{text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="flex items-center gap-2 text-xs text-slate-600">
          <TrendingUp size={14} /> Reference map generator — not investment advice.
        </p>
      </section>

      {/* Form side */}
      <section className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="animate-rise w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-600 text-white">
              <Layers size={19} />
            </div>
            <div className="text-lg font-extrabold text-white">
              Zone<span className="text-brand-400">App</span>
            </div>
          </div>

          <h2 className="text-2xl font-bold tracking-tight text-white">Sign in</h2>
          <p className="mt-1.5 text-sm text-slate-400">Use the credentials issued by your administrator.</p>

          <form onSubmit={submit} className="mt-7 space-y-4">
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Username</label>
              <div className="relative">
                <User size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-500" />
                <Input
                  className="pl-9"
                  autoFocus
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="your.username"
                  required
                />
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Password</label>
              <div className="relative">
                <Lock size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-500" />
                <Input
                  className="px-9"
                  type={show ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  className="absolute top-1/2 right-2 -translate-y-1/2 rounded-lg p-1.5 text-slate-500 hover:bg-white/5 hover:text-slate-300"
                  aria-label={show ? 'Hide password' : 'Show password'}
                >
                  {show ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>

            {error && (
              <p className="rounded-xl bg-rose-500/10 px-3 py-2.5 text-[13px] font-medium text-rose-300 ring-1 ring-rose-500/25">
                {error}
              </p>
            )}

            <Button type="submit" size="lg" loading={busy} className="w-full">
              {busy ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <p className="mt-8 text-center text-[11.5px] leading-relaxed text-slate-600">
            Sessions last 7 days. Forgotten credentials can only be reset by an administrator.
          </p>
        </div>
      </section>
    </div>
  )
}
