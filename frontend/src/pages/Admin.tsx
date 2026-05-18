import { useState, lazy, Suspense } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { ModeFilterProvider } from '../contexts/ModeFilterContext'
import { ErrorBoundary } from '../components/ErrorBoundary'


const SystemStatus = lazy(() => import('../components/admin/SystemStatus').then(m => ({ default: m.SystemStatus })))
const CopyTraderMonitor = lazy(() => import('../components/admin/CopyTraderMonitor').then(m => ({ default: m.CopyTraderMonitor })))
const Backtest = lazy(() => import('./Backtest').then(m => ({ default: m.Backtest })))
const StrategiesTab = lazy(() => import('../components/admin/StrategiesTab').then(m => ({ default: m.StrategiesTab })))
const MarketWatchTab = lazy(() => import('../components/admin/MarketWatchTab').then(m => ({ default: m.MarketWatchTab })))
const WalletConfigTab = lazy(() => import('../components/admin/WalletConfigTab').then(m => ({ default: m.WalletConfigTab })))
const CredentialsTab = lazy(() => import('../components/admin/CredentialsTab').then(m => ({ default: m.CredentialsTab })))
const TelegramTab = lazy(() => import('../components/admin/TelegramTab').then(m => ({ default: m.TelegramTab })))
const RiskTab = lazy(() => import('../components/admin/RiskTab').then(m => ({ default: m.RiskTab })))
const AITab = lazy(() => import('../components/admin/AITab').then(m => ({ default: m.AITab })))
const DebateMonitorTab = lazy(() => import('../components/admin/DebateMonitorTab').then(m => ({ default: m.DebateMonitorTab })))
const PendingApprovals = lazy(() => import('./PendingApprovals'))
const SettingsTab = lazy(() => import('../components/admin/SettingsTab'))
const TradingTerminalTab = lazy(() => import('../components/dashboard/TradingTerminalTab').then(m => ({ default: m.TradingTerminalTab })))
const WhaleTrackerTab = lazy(() => import('../components/dashboard/WhaleTrackerTab').then(m => ({ default: m.WhaleTrackerTab })))
const EdgeTrackerTab = lazy(() => import('../components/dashboard/EdgeTrackerTab').then(m => ({ default: m.EdgeTrackerTab })))
const DecisionLogTab = lazy(() => import('../components/dashboard/DecisionLogTab').then(m => ({ default: m.DecisionLogTab })))
const SettlementsTab = lazy(() => import('../components/dashboard/SettlementsTab').then(m => ({ default: m.SettlementsTab })))
const AGIControlTab = lazy(() => import('../components/admin/AGIControlTab').then(m => ({ default: m.AGIControlTab })))
const AGIDecisionsTab = lazy(() => import('../components/admin/AGIDecisionsTab').then(m => ({ default: m.AGIDecisionsTab })))
const AGIComposerTab = lazy(() => import('../components/admin/AGIComposerTab').then(m => ({ default: m.AGIComposerTab })))
const AGIRegimeTab = lazy(() => import('../components/admin/AGIRegimeTab').then(m => ({ default: m.AGIRegimeTab })))
const ActivityTimeline = lazy(() => import('../components/ActivityTimeline').then(m => ({ default: m.ActivityTimeline })))
const SystemLogsTab = lazy(() => import('../components/admin/SystemLogsTab').then(m => ({ default: m.SystemLogsTab })))

function AdminLoginGate({ login }: { login: (p: string) => Promise<void> }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!password.trim()) return
    setLoading(true)
    setError('')
    try {
      await login(password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen bg-black flex flex-col overflow-hidden font-mono">
      <div className="shrink-0 border-b border-neutral-800 px-4 py-2 flex items-center justify-between bg-black">
        <Link to="/" className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors">PolyEdge</Link>
        <span className="text-[10px] font-bold text-neutral-400 uppercase tracking-[0.2em]">Admin Dashboard</span>
        <span />
      </div>
      <div className="flex-1 flex items-center justify-center">
        <div className="w-80 border border-neutral-800 bg-neutral-950 p-6">
          <div className="text-[9px] text-neutral-600 uppercase tracking-[0.3em] mb-5">Admin Access Required</div>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Admin password"
              autoFocus
              className="w-full bg-black border border-neutral-800 text-neutral-200 text-xs px-3 py-2 focus:outline-none focus:border-green-500/40 font-mono placeholder-neutral-700"
            />
            {error && <p className="text-[10px] text-red-400">{error}</p>}
            <button
              type="submit"
              disabled={loading || !password.trim()}
              className="px-3 py-1.5 bg-green-500/10 border border-green-500/30 text-green-400 text-[10px] uppercase tracking-wider hover:bg-green-500/20 transition-colors disabled:opacity-40"
            >
              {loading ? 'Verifying...' : 'Login'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

const TABS = [
  'System', 
  'System Logs',
  'Activity Log',
  'AGI Control', 
  'AGI Decisions', 
  'AGI Regime',
  'AGI Composer',
  'Debate Monitor',
  'AI Config', 
  'Trading Terminal', 
  'Whale Tracker', 
  'Edge Tracker', 
  'Decision Log', 
  'Settlements', 
  'Backtest', 
  'Risk', 
  'Credentials', 
  'Strategies', 
  'Copy Trader', 
  'Telegram', 
  'Market Watch', 
  'Wallet Config', 
  'Settings', 
  'Pending Approvals'
] as const
type Tab = typeof TABS[number]

export default function Admin() {
  const [activeTab, setActiveTab] = useState<Tab>('System')
  const { isAuthenticated, authRequired, login, logout } = useAuth()

  if (authRequired && !isAuthenticated) {
    return <AdminLoginGate login={login} />
  }

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden font-mono">
      <div className="shrink-0 border-b border-neutral-800 px-4 py-2 flex items-center justify-between bg-black gap-2">
        <Link to="/" className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors whitespace-nowrap">PolyEdge</Link>
        <div className="flex items-center gap-3 overflow-x-auto scrollbar-none flex-nowrap">
          <Link to="/dashboard" className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors whitespace-nowrap">Dashboard</Link>
          <Link to="/mirofish" className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors whitespace-nowrap">MiroFish</Link>
          <Link to="/activity" className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors whitespace-nowrap">Activity</Link>
          <span className="text-[10px] font-bold text-neutral-400 uppercase tracking-[0.2em] whitespace-nowrap">Admin</span>
        </div>
        {authRequired ? (
          <button onClick={logout} className="text-[9px] text-neutral-600 hover:text-neutral-400 uppercase tracking-wider transition-colors whitespace-nowrap">Logout</button>
        ) : (
          <span />
        )}
      </div>

      {/* Tab Bar */}
      <div className="shrink-0 border-b border-neutral-800 flex items-center overflow-x-auto scrollbar-none flex-nowrap">
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-[10px] uppercase tracking-wider border-b-2 whitespace-nowrap transition-colors ${
              activeTab === tab
                ? 'text-green-500 border-green-500'
                : 'text-neutral-500 border-transparent hover:text-neutral-300'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 max-w-100vw">
        <ModeFilterProvider>
        <ErrorBoundary>
        <Suspense fallback={<div className="flex items-center justify-center h-full text-neutral-500">Loading...</div>}>
          {activeTab === 'System' && <SystemStatus />}
          {activeTab === 'System Logs' && <SystemLogsTab />}
          {activeTab === 'Activity Log' && <ActivityTimeline />}
          {activeTab === 'AGI Control' && <AGIControlTab />}
          {activeTab === 'AGI Decisions' && <AGIDecisionsTab />}
          {activeTab === 'AGI Regime' && <AGIRegimeTab />}
          {activeTab === 'AGI Composer' && <AGIComposerTab />}
          {activeTab === 'Debate Monitor' && <DebateMonitorTab />}
          {activeTab === 'AI Config' && <AITab />}
          {activeTab === 'Trading Terminal' && <TradingTerminalTab />}
          {activeTab === 'Whale Tracker' && <WhaleTrackerTab />}
          {activeTab === 'Edge Tracker' && <EdgeTrackerTab />}
          {activeTab === 'Decision Log' && <DecisionLogTab />}
          {activeTab === 'Settlements' && <SettlementsTab />}
          {activeTab === 'Backtest' && <Backtest />}
          {activeTab === 'Risk' && <RiskTab />}
          {activeTab === 'Credentials' && <CredentialsTab />}
          {activeTab === 'Strategies' && <StrategiesTab />}
          {activeTab === 'Copy Trader' && <CopyTraderMonitor />}
          {activeTab === 'Telegram' && <TelegramTab />}
          {activeTab === 'Market Watch' && <MarketWatchTab />}
          {activeTab === 'Wallet Config' && <WalletConfigTab />}
          {activeTab === 'Settings' && <SettingsTab />}
          {activeTab === 'Pending Approvals' && <PendingApprovals />}
        </Suspense>
        </ErrorBoundary>
        </ModeFilterProvider>
      </div>
    </div>
  )
}
