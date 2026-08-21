import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity, BarChart3, CalendarDays, CalendarRange, ChevronDown, Layers, LayoutDashboard,
  LogOut, Menu, PlayCircle, Plug, Users, X,
} from 'lucide-react'
import { useAuth } from '../lib/auth.jsx'
import { Avatar, Badge } from './ui.jsx'

export const NAV = [
  {
    section: 'Market',
    items: [
      { to: '/dashboard/overview', label: 'Overview', icon: LayoutDashboard },
      { to: '/dashboard/zones', label: 'Next-session zones', icon: Layers },
      { to: '/dashboard/base-rates', label: 'Base rates', icon: BarChart3 },
      { to: '/dashboard/gap-cpr', label: 'Gap & CPR', icon: Activity },
      { to: '/dashboard/sessions', label: 'Sessions', icon: CalendarRange },
      { to: '/dashboard/broker', label: 'My broker', icon: Plug },
    ],
  },
  {
    section: 'Administration',
    admin: true,
    items: [
      { to: '/admin/clients', label: 'Clients', icon: Users },
      { to: '/admin/brokers', label: 'Broker connections', icon: Plug },
      { to: '/admin/holidays', label: 'Market holidays', icon: CalendarDays },
      { to: '/admin/jobs', label: 'Market-close job', icon: PlayCircle },
    ],
  },
]

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-600 text-white shadow-lg shadow-brand-600/30">
        <Layers size={18} />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-extrabold tracking-tight text-white">
          Zone<span className="text-brand-400">App</span>
        </div>
        <div className="text-[10px] tracking-wider text-slate-500 uppercase">Levels & base rates</div>
      </div>
    </div>
  )
}

function NavItems({ isAdmin, onNavigate }) {
  return (
    <nav className="space-y-6">
      {NAV.filter((g) => !g.admin || isAdmin).map((group) => (
        <div key={group.section}>
          <p className="mb-2 px-3 text-[10px] font-bold tracking-[0.14em] text-slate-500 uppercase">{group.section}</p>
          <div className="space-y-1">
            {group.items.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={onNavigate}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium transition ${
                    isActive
                      ? 'bg-brand-500/15 text-white ring-1 ring-brand-500/30'
                      : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon size={16} className={isActive ? 'text-brand-400' : 'text-slate-500 group-hover:text-slate-300'} />
                    <span className="truncate">{label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  )
}

/** Horizontal tab strip — the primary switcher on small screens. */
function TabStrip({ isAdmin }) {
  const items = NAV.filter((g) => !g.admin || isAdmin).flatMap((g) => g.items)
  return (
    <div className="scrollbar-thin -mx-4 overflow-x-auto px-4 lg:hidden">
      <div className="flex w-max gap-1.5 pb-3">
        {items.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-2 rounded-full px-3.5 py-2 text-xs font-semibold whitespace-nowrap transition ${
                isActive ? 'bg-brand-600 text-white shadow-lg shadow-brand-600/25' : 'bg-white/5 text-slate-300 ring-1 ring-white/10'
              }`
            }
          >
            <Icon size={14} />
            {label}
          </NavLink>
        ))}
      </div>
    </div>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const close = () => setOpen(false)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  return (
    <div className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 rounded-xl bg-white/5 py-1.5 pr-2.5 pl-1.5 ring-1 ring-white/10 transition hover:bg-white/10"
      >
        <Avatar name={user?.display_name || user?.username} size="sm" />
        <span className="hidden text-left leading-tight sm:block">
          <span className="block max-w-[10rem] truncate text-[13px] font-semibold text-slate-100">
            {user?.display_name || user?.username}
          </span>
          <span className="block text-[10.5px] tracking-wide text-slate-500 uppercase">{user?.role}</span>
        </span>
        <ChevronDown size={15} className="text-slate-400" />
      </button>
      {open && (
        <div className="animate-rise absolute right-0 z-50 mt-2 w-60 overflow-hidden rounded-2xl border border-white/10 bg-ink-850 shadow-2xl">
          <div className="flex items-center gap-3 border-b border-white/5 px-4 py-3.5">
            <Avatar name={user?.display_name || user?.username} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-100">{user?.display_name}</p>
              <p className="truncate text-xs text-slate-500">@{user?.username}</p>
            </div>
          </div>
          <div className="px-4 py-3 text-[11px] text-slate-500">
            Symbol
            <div className="num mt-0.5 text-xs text-slate-300">{user?.symbol}</div>
          </div>
          <button
            onClick={logout}
            className="flex w-full items-center gap-2.5 border-t border-white/5 px-4 py-3 text-left text-[13px] font-semibold text-rose-300 transition hover:bg-rose-500/10"
          >
            <LogOut size={15} /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}

export default function Layout() {
  const { user, isAdmin } = useAuth()
  const [drawer, setDrawer] = useState(false)
  const location = useLocation()
  useEffect(() => setDrawer(false), [location.pathname])

  const current = NAV.flatMap((g) => g.items).find((i) => location.pathname.startsWith(i.to))

  return (
    <div className="relative z-10 flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-white/8 bg-ink-900/70 px-4 py-5 backdrop-blur-xl lg:flex">
        <Brand />
        <div className="scrollbar-thin mt-8 flex-1 overflow-y-auto pr-1">
          <NavItems isAdmin={isAdmin} />
        </div>
        <div className="rounded-xl bg-white/5 p-3 text-[11px] leading-relaxed text-slate-500 ring-1 ring-white/10">
          Reference map generator. Base rates describe the stored sample — not forecasts.
        </div>
      </aside>

      {/* Mobile drawer */}
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setDrawer(false)} />
          <aside className="animate-rise absolute top-0 left-0 flex h-full w-72 flex-col border-r border-white/10 bg-ink-900 px-4 py-5">
            <div className="flex items-center justify-between">
              <Brand />
              <button onClick={() => setDrawer(false)} className="rounded-lg p-2 text-slate-400 hover:bg-white/10">
                <X size={18} />
              </button>
            </div>
            <div className="scrollbar-thin mt-6 flex-1 overflow-y-auto">
              <NavItems isAdmin={isAdmin} onNavigate={() => setDrawer(false)} />
            </div>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 border-b border-white/8 bg-ink-950/80 backdrop-blur-xl">
          <div className="mx-auto flex w-full max-w-[1400px] items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <button
                onClick={() => setDrawer(true)}
                className="rounded-xl bg-white/5 p-2 text-slate-300 ring-1 ring-white/10 lg:hidden"
                aria-label="Open navigation"
              >
                <Menu size={18} />
              </button>
              <div className="min-w-0">
                <h1 className="truncate text-[17px] font-bold tracking-tight text-white sm:text-xl">
                  {current?.label || 'Dashboard'}
                </h1>
                <p className="num truncate text-[11px] text-slate-500">{user?.symbol}</p>
              </div>
            </div>
            <div className="flex items-center gap-2.5">
              {isAdmin && (
                <Badge tone="brand" className="hidden sm:inline-flex">
                  Admin panel
                </Badge>
              )}
              <UserMenu />
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 pt-4 pb-16 sm:px-6">
          <TabStrip isAdmin={isAdmin} />
          <Outlet />
        </main>
      </div>
    </div>
  )
}
