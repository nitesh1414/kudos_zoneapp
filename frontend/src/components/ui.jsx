import { useEffect, useRef } from 'react'
import { AlertTriangle, Inbox, Loader2, Star, X } from 'lucide-react'

export function Card({ title, subtitle, right, icon: Icon, className = '', bodyClass = '', style, children }) {
  return (
    <section className={`card animate-rise ${className}`} style={style}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 border-b border-white/5 px-4 py-3.5 sm:px-5">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-[13px] font-semibold tracking-wide text-slate-100 uppercase">
              {Icon && <Icon size={15} className="text-brand-400" />}
              <span className="truncate">{title}</span>
            </h2>
            {subtitle && <p className="mt-1 text-xs leading-relaxed text-slate-400">{subtitle}</p>}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </header>
      )}
      <div className={`px-4 py-4 sm:px-5 ${bodyClass}`}>{children}</div>
    </section>
  )
}

const toneMap = {
  neutral: 'bg-white/5 text-slate-300 ring-white/10',
  brand: 'bg-brand-500/15 text-brand-400 ring-brand-500/30',
  up: 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30',
  down: 'bg-rose-500/15 text-rose-400 ring-rose-500/30',
  warn: 'bg-amber-500/15 text-amber-400 ring-amber-500/30',
}

export function Badge({ tone = 'neutral', children, className = '' }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap ring-1 ring-inset ${toneMap[tone]} ${className}`}
    >
      {children}
    </span>
  )
}

export function Dot({ tone = 'neutral' }) {
  const c = { up: 'bg-emerald-400', down: 'bg-rose-400', warn: 'bg-amber-400', neutral: 'bg-slate-400', brand: 'bg-brand-400' }[tone]
  return <span className={`inline-block size-2 rounded-full ${c} shadow-[0_0_0_3px] shadow-current/10`} />
}

export function Stat({ label, value, hint, icon: Icon, tone = 'neutral' }) {
  const ring = {
    neutral: 'text-slate-300 bg-white/5',
    up: 'text-emerald-400 bg-emerald-500/10',
    down: 'text-rose-400 bg-rose-500/10',
    warn: 'text-amber-400 bg-amber-500/10',
    brand: 'text-brand-400 bg-brand-500/10',
  }[tone]
  return (
    <div className="card animate-rise flex items-center gap-3.5 px-4 py-3.5">
      {Icon && (
        <div className={`grid size-10 shrink-0 place-items-center rounded-xl ${ring}`}>
          <Icon size={18} />
        </div>
      )}
      <div className="min-w-0">
        <div className="truncate text-[11px] font-medium tracking-wider text-slate-400 uppercase">{label}</div>
        <div className="num mt-0.5 truncate text-xl font-bold text-slate-50">{value}</div>
        {hint && <div className="mt-0.5 truncate text-[11px] text-slate-500">{hint}</div>}
      </div>
    </div>
  )
}

export function Stars({ n = 0, className = '' }) {
  return (
    <span className={`inline-flex items-center gap-0.5 ${className}`} title={`${n} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} size={12} className={i <= n ? 'fill-amber-400 text-amber-400' : 'text-slate-700'} />
      ))}
    </span>
  )
}

export function Button({ variant = 'primary', size = 'md', icon: Icon, loading, children, className = '', ...rest }) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60'
  const sizes = { sm: 'px-2.5 py-1.5 text-xs', md: 'px-3.5 py-2 text-[13px]', lg: 'px-4 py-2.5 text-sm' }[size]
  const variants = {
    primary: 'bg-brand-600 text-white shadow-lg shadow-brand-600/25 hover:bg-brand-500',
    ghost: 'bg-white/5 text-slate-200 ring-1 ring-inset ring-white/10 hover:bg-white/10',
    subtle: 'text-slate-300 hover:bg-white/5',
    danger: 'bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30 hover:bg-rose-500/25',
  }[variant]
  return (
    <button className={`${base} ${sizes} ${variants} ${className}`} disabled={loading || rest.disabled} {...rest}>
      {loading ? <Loader2 size={15} className="animate-spin" /> : Icon ? <Icon size={15} /> : null}
      {children}
    </button>
  )
}

export function IconButton({ icon: Icon, label, tone = 'ghost', ...rest }) {
  const tones = {
    ghost: 'text-slate-300 hover:bg-white/10 ring-white/10',
    danger: 'text-rose-300 hover:bg-rose-500/20 ring-rose-500/25',
  }[tone]
  return (
    <button
      title={label}
      aria-label={label}
      className={`grid size-8 place-items-center rounded-lg ring-1 ring-inset transition active:scale-95 ${tones}`}
      {...rest}
    >
      <Icon size={15} />
    </button>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-semibold tracking-wide text-slate-400 uppercase">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-slate-500">{hint}</span>}
    </label>
  )
}

const inputCls =
  'w-full rounded-xl border border-white/10 bg-ink-900/80 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 transition focus:border-brand-500/60 focus:ring-2 focus:ring-brand-500/25 focus:outline-none'

export const Input = ({ className = '', ...rest }) => <input className={`${inputCls} ${className}`} {...rest} />
export const Select = ({ className = '', children, ...rest }) => (
  <select className={`${inputCls} ${className}`} {...rest}>
    {children}
  </select>
)

export function Modal({ open, onClose, title, subtitle, icon: Icon, children, footer, width = 'max-w-lg' }) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => e.target === ref.current && onClose()}
      className={`m-auto w-[calc(100vw-2rem)] ${width} rounded-2xl border border-white/10 bg-ink-850 p-0 text-slate-100 shadow-2xl backdrop:bg-black/60`}
    >
      <div className="flex items-start justify-between gap-4 border-b border-white/5 px-5 py-4">
        <div className="flex items-start gap-3">
          {Icon && (
            <div className="grid size-9 place-items-center rounded-xl bg-brand-500/15 text-brand-400">
              <Icon size={17} />
            </div>
          )}
          <div>
            <h3 className="text-base font-bold">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
        </div>
        <IconButton icon={X} label="Close" onClick={onClose} />
      </div>
      <div className="scrollbar-thin max-h-[65vh] overflow-y-auto px-5 py-4">{children}</div>
      {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-white/5 px-5 py-4">{footer}</div>}
    </dialog>
  )
}

export function Empty({ icon: Icon = Inbox, title, hint, action }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-4 py-10 text-center">
      <div className="grid size-12 place-items-center rounded-2xl bg-white/5 text-slate-500">
        <Icon size={22} />
      </div>
      <div>
        <p className="text-sm font-semibold text-slate-300">{title}</p>
        {hint && <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-slate-500">{hint}</p>}
      </div>
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  return (
    <Empty
      icon={AlertTriangle}
      title="Could not load this section"
      hint={error?.message || 'Unexpected error'}
      action={onRetry && <Button variant="ghost" onClick={onRetry}>Try again</Button>}
    />
  )
}

export function Skeleton({ className = 'h-4 w-full' }) {
  return <div className={`skeleton rounded-md ${className}`} />
}

export function TableWrap({ children, className = '' }) {
  return (
    <div className={`scrollbar-thin -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0 ${className}`}>
      <table className="w-full min-w-[36rem] border-collapse text-sm">{children}</table>
    </div>
  )
}

export const Th = ({ children, className = '' }) => (
  <th
    className={`border-b border-white/10 px-3 py-2.5 text-left text-[10.5px] font-semibold tracking-wider text-slate-400 uppercase ${className}`}
  >
    {children}
  </th>
)

export const Td = ({ children, className = '' }) => (
  <td className={`border-b border-white/5 px-3 py-2.5 text-slate-200 ${className}`}>{children}</td>
)

export function Note({ children }) {
  if (!children) return null
  return <p className="mt-3 text-[11.5px] leading-relaxed text-slate-500 italic">{children}</p>
}

const AVATAR_GRADIENTS = [
  'from-indigo-500 to-violet-500',
  'from-emerald-500 to-teal-500',
  'from-rose-500 to-orange-500',
  'from-sky-500 to-cyan-500',
  'from-fuchsia-500 to-pink-500',
  'from-amber-500 to-yellow-500',
]

/** Colourful initials avatar — deterministic colour per name. */
export function Avatar({ name = '', size = 'md', className = '' }) {
  const seed = [...String(name)].reduce((a, c) => a + c.charCodeAt(0), 0)
  const gradient = AVATAR_GRADIENTS[seed % AVATAR_GRADIENTS.length]
  const sizes = { sm: 'size-8 text-[11px]', md: 'size-10 text-xs', lg: 'size-12 text-sm' }[size]
  const label =
    String(name)
      .split(/[\s._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join('') || '?'
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-full bg-gradient-to-br ${gradient} ${sizes} font-bold text-white ring-2 ring-white/10 ${className}`}
    >
      {label}
    </span>
  )
}
