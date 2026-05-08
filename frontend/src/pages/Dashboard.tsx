import { POLL } from '../polling'
import { useState, useEffect, lazy, Suspense, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Link } from 'react-router-dom'
import {
  fetchDashboard, runScan, simulateTrade, startBot, stopBot, getWsUrl,
} from '../api'
import { StatsCards } from '../components/StatsCards'
import { LoginModal } from '../components/LoginModal'
import { useAuth } from '../hooks/useAuth'
import { useStats } from '../hooks/useStats'
import { useWebSocket } from '../hooks/useWebSocket'
import { ModeFilterProvider } from '../contexts/ModeFilterContext'
import { ModeSelector } from '../components/dashboard/ModeSelector'

const OverviewTab = lazy(() => import('../components/dashboard/OverviewTab').then(m => ({ default: m.OverviewTab })))
const TradesTab = lazy(() => import('../components/dashboard/TradesTab').then(m => ({ default: m.TradesTab })))
const MarketsTab = lazy(() => import('../components/dashboard/MarketsTab').then(m => ({ default: m.MarketsTab })))
const PerformanceTab = lazy(() => import('../components/dashboard/PerformanceTab').then(m => ({ default: m.PerformanceTab })))
const BrainGraph = lazy(() => import('../components/BrainGraph'))
const HFTTab = lazy(() => import('../components/hft').then(m => ({ default: m.default })))
const ControlRoomTab = lazy(() => import('../components/dashboard/ControlRoomTab').then(m => ({ default: m.ControlRoomTab })))
const KanbanTab = lazy(() => import('../components/dashboard/KanbanTab').then(m => ({ default: m.KanbanTab })))
const GlobeView = lazy(() => import('../components/GlobeView').then(m => ({ default: m.GlobeView })))

// ── Shared Helpers ────────────────────────────────────────────────────────────

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])
  return (
    <span className="text-xs tabular-nums text-neutral-400">
      {time.toLocaleTimeString('en-US', { hour12: false })}
    </span>
  )
}

function RefreshBar({ interval }: { interval: number }) {
  const [progress, setProgress] = useState(100)
  useEffect(() => {
    setProgress(100)
    const step = 100 / (interval / 1000)
    const timer = setInterval(() => {
      setProgress(p => Math.max(0, p - step))
    }, 1000)
    return () => clearInterval(timer)
  }, [interval])
  return (
    <div className="refresh-bar w-16">
      <div className="refresh-fill" style={{ width: `${progress}%` }} />
    </div>
  )
}

// ── MAIN DASHBOARD ────────────────────────────────────────────────────────────

const DASHBOARD_TABS = ['Overview', 'Control Room', 'AGI Pipeline', 'Performance', 'Brain', 'Trades', 'Markets', 'Globe', 'HFT'] as const
type DashboardTab = typeof DASHBOARD_TABS[number]

export default function Dashboard() {
  const queryClient = useQueryClient()
  const { isAuthenticated, authRequired, login, logout } = useAuth()
  const [showLogin, setShowLogin] = useState(false)
  const [activeTab, setActiveTab] = useState<DashboardTab>('Overview')

  const requireAdminAction = (action: () => void) => {
    if (!isAuthenticated) {
      setShowLogin(true)
      return
    }
    action()
  }

  const unifiedStats = useStats()
  const wsUrl = useMemo(() => getWsUrl('/ws/markets'), [])
  const { status: wsStatus, reconnectAttempt, maxReconnectAttempts } = useWebSocket(wsUrl, { topic: 'markets' })

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: POLL.NORMAL,
  })

  const scanMutation = useMutation({
    mutationFn: runScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['stats-unified'] })
    },
  })

  const tradeMutation = useMutation({
    mutationFn: simulateTrade,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['stats-unified'] })
    },
  })

  const startMutation = useMutation({
    mutationFn: startBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['stats-unified'] })
    },
  })

  const stopMutation = useMutation({
    mutationFn: stopBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['stats-unified'] })
    },
  })

  const activeSignals = data?.active_signals ?? []
  const recentTrades = data?.recent_trades ?? []
  const topWinningTrades = data?.top_winning_trades ?? []
  const btcPrice = data?.btc_price
  const micro = data?.microstructure
  const windows = data?.windows ?? []
  const weatherSignals = data?.weather_signals ?? []
  const weatherForecasts = data?.weather_forecasts ?? []

  const equityCurve = data?.equity_curve ?? []
  const calibration = data?.calibration ?? null

  if (isLoading) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" />
          </div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Initializing</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-xs uppercase mb-2 tracking-wider">Connection Error</div>
          <button onClick={() => refetch()} className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider">
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <ModeFilterProvider>
      <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
        {/* NAVBAR */}
        <motion.header
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4 relative overflow-x-auto scrollbar-none"
        >
          <div className="scan-line" />
          <div className="flex items-center gap-2 shrink-0 whitespace-nowrap">
            <Link to="/admin" className="text-[9px] text-neutral-600 hover:text-green-500 uppercase tracking-wider transition-colors mr-1">Admin</Link>
            <h1 className="text-xs font-bold text-neutral-100 uppercase tracking-widest whitespace-nowrap font-mono">PolyEdge</h1>
            <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase border ${unifiedStats.isRunning ? 'bg-cyan-500/10 text-cyan-500 border-cyan-500/20' : 'bg-neutral-800 text-neutral-500 border-neutral-700'}`}>
              {unifiedStats.isRunning ? 'Active' : 'Offline'}
            </span>
            {(() => {
              const mode = unifiedStats.mode || 'paper'
              const cfg: Record<string, { label: string; cls: string }> = {
                paper: { label: 'Paper', cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
                testnet: { label: 'Testnet', cls: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
                live: { label: 'LIVE', cls: 'bg-red-500/10 text-red-500 border-red-500/20' },
              }
              const { label, cls } = cfg[mode] || cfg['paper']
              return <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase border ${cls}`}>{label}</span>
            })()}
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <Link to="/mirofish" className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors whitespace-nowrap">MiroFish</Link>
            <Link to="/activity" className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors whitespace-nowrap">Activity</Link>
          </div>

          {btcPrice && (
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-sm font-bold tabular-nums text-neutral-100">${(btcPrice.price ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
              <span className={`text-[10px] tabular-nums ${(btcPrice.change_24h ?? 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {(btcPrice.change_24h ?? 0) >= 0 ? '+' : ''}{(btcPrice.change_24h ?? 0).toFixed(2)}%
              </span>
            </div>
          )}

          <div className="flex-1" />
          <div className="hidden lg:block"><StatsCards /></div>

          <div className="flex items-center gap-2 shrink-0">
            {authRequired && (
              isAuthenticated ? (
                <button onClick={logout} className="px-2 py-1 text-[9px] text-neutral-600 border border-neutral-800 hover:border-neutral-700 hover:text-neutral-400 uppercase tracking-wider transition-colors">Logout</button>
              ) : (
                <button onClick={() => setShowLogin(true)} className="px-2 py-1 text-[9px] text-neutral-500 border border-neutral-700 hover:border-green-500/40 hover:text-green-400 uppercase tracking-wider transition-colors">Login</button>
              )
            )}
            <LiveClock />
          </div>

          <AnimatePresence>
            {showLogin && (
              <LoginModal login={login} onSuccess={() => setShowLogin(false)} onCancel={() => setShowLogin(false)} />
            )}
          </AnimatePresence>
        </motion.header>

        {/* COMPACT STATS — mobile only */}
        <div className="lg:hidden shrink-0 border-b border-neutral-800 px-3 py-1 flex items-center gap-3 overflow-x-auto scrollbar-none">
          <StatsCards />
        </div>

        {/* MODE SELECTOR */}
        {(['Overview', 'Trades', 'Performance'] as const).includes(activeTab) && <ModeSelector />}

        {/* TAB BAR */}
        <div className="shrink-0 border-b border-neutral-800 px-3 flex items-center gap-0 overflow-x-auto scrollbar-none">
          {DASHBOARD_TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-1.5 text-[10px] uppercase tracking-wider border-b-2 whitespace-nowrap transition-colors ${
                activeTab === tab
                  ? 'text-green-500 border-green-500'
                  : 'text-neutral-500 border-transparent hover:text-neutral-300'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* TAB CONTENT */}
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          <Suspense fallback={<div className="flex items-center justify-center h-full text-neutral-500">Loading...</div>}>
            {activeTab === 'Overview' && (
              <OverviewTab
                data={data}
                equityCurve={equityCurve}
                activeSignals={activeSignals}
                recentTrades={recentTrades}
                topWinningTrades={topWinningTrades}
                weatherSignals={weatherSignals}
                weatherForecasts={weatherForecasts}
                calibration={calibration}
                windows={windows}
                micro={micro ?? null}
                onSimulateTrade={(ticker) => requireAdminAction(() => tradeMutation.mutate(ticker))}
                isSimulating={tradeMutation.isPending}
                onStart={() => requireAdminAction(() => startMutation.mutate())}
                onStop={() => requireAdminAction(() => stopMutation.mutate())}
                onScan={() => requireAdminAction(() => scanMutation.mutate())}
              />
            )}
            {activeTab === 'Performance' && <PerformanceTab />}
            {activeTab === 'Control Room' && <ControlRoomTab isAdmin={isAuthenticated} onLoginRequired={() => setShowLogin(true)} />}
            {activeTab === 'AGI Pipeline' && <KanbanTab isAdmin={isAuthenticated} />}
            {activeTab === 'Brain' && <BrainGraph />}
            {activeTab === 'Trades' && <TradesTab />}
            {activeTab === 'Markets' && <MarketsTab />}
            {activeTab === 'Globe' && (
              <Suspense fallback={<div className="flex items-center justify-center h-full text-neutral-500 animate-pulse bg-gray-800/50 rounded-lg">Loading Globe...</div>}>
                <GlobeView forecasts={weatherForecasts} signals={weatherSignals} />
              </Suspense>
            )}
            {activeTab === 'HFT' && <HFTTab />}
          </Suspense>
        </div>

        {/* FOOTER */}
        <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 overflow-hidden">
          <span className="text-[10px] text-neutral-700 font-mono whitespace-nowrap hidden sm:inline">Binance/Coinbase | Open-Meteo | Polymarket + Kalshi</span>
          <span className="text-[10px] text-neutral-700 font-mono whitespace-nowrap sm:hidden">Binance · Open-Meteo · Polymarket</span>
          <div className="flex flex-wrap items-center gap-3">
            <RefreshBar interval={10000} />
            <span className="text-[10px] text-neutral-700 font-mono whitespace-nowrap hidden sm:inline">Copy · Weather · Kalshi · BTC Oracle · BTC 5m</span>
            <span className="text-[10px] text-neutral-700 font-mono whitespace-nowrap sm:hidden">Copy · Weather · BTC</span>
            <div className="flex items-center gap-1">
              <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                wsStatus === 'connected' ? 'bg-green-500' : 
                wsStatus === 'reconnecting' ? 'bg-yellow-500' : 
                'bg-red-400'
              }`} />
              <span className={`text-[10px] font-mono ${
                wsStatus === 'connected' ? 'text-neutral-600' : 
                wsStatus === 'reconnecting' ? 'text-yellow-400' : 
                'text-red-400'
              }`}>
                {wsStatus === 'connected' ? 'Connected' : 
                 wsStatus === 'connecting' ? 'Connecting...' : 
                 wsStatus === 'reconnecting' ? `Reconnecting (${reconnectAttempt}/${maxReconnectAttempts})` :
                 'Disconnected'}
              </span>
            </div>
          </div>
        </footer>
      </div>
    </ModeFilterProvider>
  )
}
