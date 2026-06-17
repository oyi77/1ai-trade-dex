import { useMemo } from 'react'
import { POLL } from '../../polling'
import { useQuery } from '@tanstack/react-query'
import { useStats } from '../../hooks/useStats'
import { useModeFilter } from '../../hooks/useModeFilter'
import { fetchHealth, fetchTrades, fetchStrategyStats, fetchStrategies, fetchDashboard } from '../../api'
import type { StrategyHealth, StrategyPnL } from '../../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { EquityChart } from '../EquityChart'

export function PerformanceTab() {
  const { pnl, bankroll, winRate } = useStats()
  const { selectedMode } = useModeFilter()

  const { data: dashboardData } = useQuery({
    queryKey: ['dashboard-equity-perf'],
    queryFn: fetchDashboard,
    refetchInterval: POLL.SLOW,
  })

  const initialBankroll = dashboardData?.stats?.initial_bankroll ?? 10000

  const { data: health } = useQuery({
    queryKey: ['health-perf'],
    queryFn: fetchHealth,
    refetchInterval: POLL.SLOW,
  })

  const { data: allTrades = [] } = useQuery({
    queryKey: ['trades-perf'],
    queryFn: () => fetchTrades(),
    refetchInterval: POLL.SLOW,
  })

  const { data: strategyStatsData } = useQuery({
    queryKey: ['strategy-stats'],
    queryFn: fetchStrategyStats,
    refetchInterval: POLL.VERY_SLOW,
  })

  const { data: strategiesConfig = [] } = useQuery({
    queryKey: ['strategies-config'],
    queryFn: fetchStrategies,
    refetchInterval: POLL.VERY_SLOW,
  })

  const strategies: StrategyHealth[] = health?.strategies ?? []
  const strategyPnL: StrategyPnL[] = strategyStatsData?.strategies ?? []
  const todayKey = new Date().toDateString()

  // Filter trades by selected mode before calculating metrics
  // ⚡ Bolt: Memoized derived state to prevent O(N) recalculation on every render
  const filteredTrades = useMemo(() =>
    allTrades.filter((t) => selectedMode === 'all' || t.trading_mode === selectedMode),
  [allTrades, selectedMode])

  // Filter equity curve by selected mode
  const filteredEquityCurve = useMemo(() => dashboardData?.equity_curve ?? [], [dashboardData])

  // ⚡ Bolt: Memoized complex trade filtering for mode metrics (Optimized to single O(N) loop)
  const chartData = useMemo(() => {
    let paperWins = 0, paperSettled = 0, liveWins = 0, liveSettled = 0

    for (let i = 0; i < filteredTrades.length; i++) {
      const t = filteredTrades[i]
      if (t.trading_mode === 'paper') {
        if (t.result === 'win') {
          paperWins++
          paperSettled++
        } else if (t.result === 'loss') {
          paperSettled++
        }
      } else if (t.trading_mode === 'live') {
        if (t.result === 'win') {
          liveWins++
          liveSettled++
        } else if (t.result === 'loss') {
          liveSettled++
        }
      }
    }

    return [
      { name: 'Paper', winRate: paperSettled > 0 ? (paperWins / paperSettled) * 100 : 0 },
      { name: 'Live', winRate: liveSettled > 0 ? (liveWins / liveSettled) * 100 : 0 },
    ]
  }, [filteredTrades])

  // ⚡ Bolt: Memoized daily PNL reduction
  const dailyPnl = useMemo(() => {
    const todayStart = new Date(todayKey)
    todayStart.setHours(0, 0, 0, 0)
    return filteredTrades
      .filter((t) => t.timestamp && new Date(t.timestamp) >= todayStart)
      .reduce((s: number, t) => s + (t.pnl ?? 0), 0)
  }, [filteredTrades, todayKey])

  // ⚡ Bolt: Memoized average trade size computation
  const avgTradeSize = useMemo(() =>
    filteredTrades.length > 0
      ? filteredTrades.reduce((s: number, t) => s + (t.size ?? 0), 0) / filteredTrades.length
      : 0,
  [filteredTrades])

  // Filter strategy stats by selected mode
  const filteredStrategyPnL = strategyPnL

  // ⚡ Bolt: Memoized aggregated strategy stats to avoid reduce loops on re-render
  const { totalWins, totalLosses, totalPending, totalPnlSum, totalTrades, overallWinRate } = useMemo(() => {
    const totalWins = filteredStrategyPnL.reduce((s, r) => s + r.wins, 0)
    const totalLosses = filteredStrategyPnL.reduce((s, r) => s + r.losses, 0)
    const totalPending = filteredStrategyPnL.reduce((s, r) => s + r.pending, 0)
    const totalPnlSum = filteredStrategyPnL.reduce((s, r) => s + r.total_pnl, 0)
    const totalTrades = totalWins + totalLosses
    const overallWinRate = totalTrades > 0 ? totalWins / totalTrades : 0
    return { totalWins, totalLosses, totalPending, totalPnlSum, totalTrades, overallWinRate }
  }, [filteredStrategyPnL])

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto h-full">
      {/* Equity Chart */}
      <div>
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Equity Curve</div>
        <div className="border border-neutral-800 bg-neutral-900/20" style={{ height: '200px' }}>
          <EquityChart data={filteredEquityCurve} initialBankroll={initialBankroll} />
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div>
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Key Metrics</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
           {[
            { label: 'Bankroll', value: `$${bankroll.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, color: 'text-neutral-200' },
            { label: 'Total PNL', value: `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`, color: pnl >= 0 ? 'text-green-500' : 'text-red-500' },
            { label: 'Win Rate', value: `${winRate.toFixed(1)}%`, color: winRate >= 50 ? 'text-green-500' : 'text-amber-400' },
            { label: 'Total Trades', value: String(filteredTrades.length), color: 'text-neutral-300' },
            { label: 'Avg Trade Size', value: `$${avgTradeSize.toFixed(0)}`, color: 'text-neutral-300' },
            { label: 'Daily PNL', value: `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`, color: dailyPnl >= 0 ? 'text-green-500' : 'text-red-500' },
          ].map(m => (
            <div key={m.label} className="border border-neutral-800 bg-neutral-900/20 p-3">
              <div className="text-[9px] text-neutral-600 uppercase tracking-wider mb-1">{m.label}</div>
              <div className={`text-sm font-semibold tabular-nums font-mono ${m.color}`}>{m.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Strategy P&L Table */}
      <div>
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Strategy P&L Breakdown</div>
        <div className="border border-neutral-800">
          {/* Header */}
          <div className="grid grid-cols-[1fr_48px_60px_48px_72px_64px] gap-0 border-b border-neutral-800 px-3 py-1.5 bg-neutral-900/40">
            {['Strategy', 'Trades', 'W/L', 'Pend', 'Win%', 'PnL'].map(h => (
              <div key={h} className="text-[9px] text-neutral-600 uppercase tracking-wider text-right first:text-left">{h}</div>
            ))}
          </div>

          {/* Rows */}
          {strategyPnL.length === 0 ? (
            <div className="text-[10px] text-neutral-600 px-3 py-3">
              No strategy data — trades will appear here after the bot runs
            </div>
          ) : (
            <>
              {filteredStrategyPnL.map((row) => {
                const settled = row.wins + row.losses
                return (
                  <div
                    key={row.strategy}
                    className="grid grid-cols-[1fr_48px_60px_48px_72px_64px] gap-0 border-b border-neutral-800/50 px-3 py-1.5 hover:bg-neutral-900/30"
                  >
                    <div className="text-[10px] text-neutral-300 font-mono truncate">{row.strategy}</div>
                    <div className="text-[10px] text-neutral-400 tabular-nums text-right">{row.total_trades}</div>
                    <div className="text-[10px] text-neutral-400 tabular-nums text-right">
                      <span className="text-green-600">{row.wins}</span>
                      <span className="text-neutral-600">/</span>
                      <span className="text-red-600">{row.losses}</span>
                    </div>
                    <div className="text-[10px] text-neutral-500 tabular-nums text-right">{row.pending}</div>
                    <div className={`text-[10px] tabular-nums text-right ${(row.win_rate ?? 0) >= 0.5 ? 'text-green-500' : settled === 0 ? 'text-neutral-500' : 'text-amber-400'}`}>
                      {settled === 0 ? '—' : `${((row.win_rate ?? 0) * 100).toFixed(1)}%`}
                    </div>
                    <div className={`text-[10px] tabular-nums font-mono text-right ${(row.total_pnl ?? 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                      {(row.total_pnl ?? 0) >= 0 ? '+' : ''}{(row.total_pnl ?? 0).toFixed(2)}
                    </div>
                  </div>
                )
              })}

              {/* Totals row */}
              <div className="grid grid-cols-[1fr_48px_60px_48px_72px_64px] gap-0 px-3 py-1.5 bg-neutral-900/40">
                <div className="text-[9px] text-neutral-500 uppercase tracking-wider">Total</div>
                <div className="text-[10px] text-neutral-300 tabular-nums text-right font-semibold">{filteredStrategyPnL.reduce((s, r) => s + r.total_trades, 0)}</div>
                <div className="text-[10px] tabular-nums text-right font-semibold">
                  <span className="text-green-500">{totalWins}</span>
                  <span className="text-neutral-600">/</span>
                  <span className="text-red-500">{totalLosses}</span>
                </div>
                <div className="text-[10px] text-neutral-500 tabular-nums text-right">{totalPending}</div>
                <div className={`text-[10px] tabular-nums text-right font-semibold ${overallWinRate >= 0.5 ? 'text-green-500' : totalTrades === 0 ? 'text-neutral-500' : 'text-amber-400'}`}>
                  {totalTrades === 0 ? '—' : `${(overallWinRate * 100).toFixed(1)}%`}
                </div>
                <div className={`text-[10px] tabular-nums font-mono text-right font-semibold ${totalPnlSum >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {totalPnlSum >= 0 ? '+' : ''}{totalPnlSum.toFixed(2)}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Win Rate Chart */}
      <div>
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Win Rate by Mode</div>
        <div className="border border-neutral-800 bg-neutral-900/20 p-3" style={{ height: '140px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#737373' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#737373' }} axisLine={false} tickLine={false} domain={[0, 100]} unit="%" />
              <Tooltip
                contentStyle={{ background: '#0a0a0a', border: '1px solid #262626', borderRadius: 0, fontSize: 10 }}
                formatter={(v: number) => [`${v.toFixed(1)}%`, 'Win Rate']}
              />
              <Bar dataKey="winRate" radius={0}>
                {chartData.map((entry, index) => (
                  <Cell key={index} fill={entry.winRate >= 50 ? '#22c55e' : '#f59e0b'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Strategy Health */}
      <div>
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Strategy Health</div>
        <div className="space-y-1">
          {strategies.map((s: StrategyHealth) => (
            <div key={s.name} className="border border-neutral-800 px-3 py-2 flex items-center gap-4">
              <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.healthy ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-[10px] text-neutral-300 font-mono flex-1">{s.name}</span>
              <span className="text-[9px] text-neutral-600">
                {s.last_heartbeat ? new Date(s.last_heartbeat).toLocaleTimeString('en-US', { hour12: false }) : 'never'}
              </span>
              {s.lag_seconds != null && (
                <span className={`text-[9px] tabular-nums ${s.lag_seconds > 120 ? 'text-red-400' : 'text-neutral-500'}`}>
                  {s.lag_seconds.toFixed(0)}s lag
                </span>
              )}
              <span className={`text-[9px] uppercase tracking-wider ${s.healthy ? 'text-green-500' : 'text-red-500'}`}>
                {s.healthy ? 'healthy' : 'stale'}
              </span>
            </div>
          ))}
          {strategies.length === 0 && (
            <div className="text-[10px] text-neutral-600 py-2">
              Bot not running — start from Admin panel
            </div>
          )}
        </div>
      </div>

      {/* Active Strategies Status */}
      <div>
        <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Active Strategies Status</div>
        <div className="border border-neutral-800">
          {strategiesConfig.length === 0 ? (
            <div className="text-[10px] text-neutral-600 px-3 py-3">No strategy config loaded</div>
          ) : (
            strategiesConfig.map((cfg, idx) => (
              <div
                key={cfg.name}
                className={`flex items-center gap-3 px-3 py-2 ${idx < strategiesConfig.length - 1 ? 'border-b border-neutral-800/50' : ''}`}
              >
                <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.enabled ? 'bg-green-500' : 'bg-neutral-700'}`} />
                <span className="text-[10px] text-neutral-300 font-mono flex-1">{cfg.name}</span>
                <span className="text-[9px] text-neutral-600 tabular-nums">
                  {cfg.interval_seconds < 60
                    ? `every ${cfg.interval_seconds}s`
                    : `every ${Math.round(cfg.interval_seconds / 60)}min`}
                </span>
                <span className={`text-[9px] uppercase tracking-wider font-mono ${cfg.enabled ? 'text-green-500' : 'text-neutral-600'}`}>
                  {cfg.enabled ? 'active' : 'disabled'}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
