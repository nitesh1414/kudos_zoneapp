import { Navigate, Route, Routes } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from './lib/auth.jsx'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Overview from './pages/Overview.jsx'
import Zones from './pages/Zones.jsx'
import BaseRates from './pages/BaseRates.jsx'
import GapCpr from './pages/GapCpr.jsx'
import Sessions from './pages/Sessions.jsx'
import MyBroker from './pages/MyBroker.jsx'
import Clients from './pages/admin/Clients.jsx'
import Symbols from './pages/admin/Symbols.jsx'
import Seeding from './pages/admin/Seeding.jsx'
import Brokers from './pages/admin/Brokers.jsx'
import Holidays from './pages/admin/Holidays.jsx'
import Jobs from './pages/admin/Jobs.jsx'

function Splash() {
  return (
    <div className="relative z-10 grid min-h-screen place-items-center">
      <div className="flex items-center gap-3 text-slate-400">
        <Loader2 className="animate-spin" size={20} /> Loading workspace…
      </div>
    </div>
  )
}

function Protected({ adminOnly = false, children }) {
  const { user, loading, isAdmin } = useAuth()
  if (loading) return <Splash />
  if (!user) return <Navigate to="/login" replace />
  if (adminOnly && !isAdmin) return <Navigate to="/dashboard/overview" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route path="/dashboard/overview" element={<Overview />} />
        <Route path="/dashboard/zones" element={<Zones />} />
        <Route path="/dashboard/base-rates" element={<BaseRates />} />
        <Route path="/dashboard/gap-cpr" element={<GapCpr />} />
        <Route path="/dashboard/sessions" element={<Sessions />} />
        <Route path="/dashboard/broker" element={<MyBroker />} />
        <Route
          path="/admin/clients"
          element={
            <Protected adminOnly>
              <Clients />
            </Protected>
          }
        />
        <Route
          path="/admin/symbols"
          element={
            <Protected adminOnly>
              <Symbols />
            </Protected>
          }
        />
        <Route
          path="/admin/seeding"
          element={
            <Protected adminOnly>
              <Seeding />
            </Protected>
          }
        />
        <Route
          path="/admin/brokers"
          element={
            <Protected adminOnly>
              <Brokers />
            </Protected>
          }
        />
        <Route
          path="/admin/holidays"
          element={
            <Protected adminOnly>
              <Holidays />
            </Protected>
          }
        />
        <Route
          path="/admin/jobs"
          element={
            <Protected adminOnly>
              <Jobs />
            </Protected>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard/overview" replace />} />
    </Routes>
  )
}
