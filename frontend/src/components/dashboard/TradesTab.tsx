import { POLL } from '../../polling'
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchTrades } from '../../api'
import { useModeFilter } from '../../hooks/useModeFilter'

export function TradesTab() {
  const [page, setPage] = useState(0)
  const { selectedMode } = useModeFilter()
  const [resultFilter, setResultFilter] = useState<string>('all')
  const [strategyFilter, setStrategyFilter] = useState<string>('all')
  const PER_PAGE = 50

  const { data: trades = [], isLoading, error } = useQuery({
    queryKey: ['trades-full'],
    queryFn: () => fetchTrades(),
    refetchInterval: POLL.NORMAL,
  })

  // Bolt: Memoize filtered trades to avoid expensive O(n) filtering on every render
  const filtered = useMemo(() => {
    return (trades || []).filter((t: any) => {
      if (selectedMode !== 'all' && t.trading_mode !== selectedMode) return false
      if (resultFilter !== 'all' && t.result !== resultFilter) return false
      if (strategyFilter !== 'all' && t.strategy !== strategyFilter) return false
      return true
    })
  }, [trades, selectedMode, resultFilter, strategyFilter])

  // Bolt: Memoize strategies extraction
  const strategies = useMemo(() => {
    return Array.from(new Set((trades || []).map((t: any) => t.strategy).filter(Boolean)))
  }, [trades])

  // Bolt: Memoize paginated view so changing page is O(1) slice of cached array
  const paginated = useMemo(() => {
    return filtered.slice(page * PER_PAGE, (page + 1) * PER_PAGE)
  }, [filtered, page])

  const totalPages = Math.ceil(filtered.length / PER_PAGE)

  // Bolt: Memoize metrics to prevent redundant reductions on page change
  const { totalPnl, wins, losses, winRate } = useMemo(() => {
    const _totalPnl = filtered.reduce((s, t: any) => s + (t.pnl ?? 0), 0)
    let _wins = 0
    let _losses = 0
    let _settledCount = 0

    for (const t of filtered) {
      if (t.result === 'win') {
        _wins++
        _settledCount++
      } else if (t.result === 'loss') {
        _losses++
        _settledCount++
      }
    }

    const _winRate = _settledCount > 0 ? (_wins / _settledCount * 100) : 0

    return {
      totalPnl: _totalPnl,
      wins: _wins,
      losses: _losses,
      winRate: _winRate
    }
  }, [filtered])

  if (isLoading) return <div className="flex items-center justify-center h-64 text-neutral-500 text-sm">Loading...</div>
  if (error) return <div className="flex items-center justify-center h-64 text-red-500/60 text-sm">Failed to load data</div>

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Filter row */}
      <div className="shrink-0 flex items-center gap-3 px-3 py-2 border-b border-neutral-800 bg-neutral-950">
        <span className="text-[9px] text-neutral-600 uppercase tracking-wider">Filters</span>
        <select value={resultFilter} onChange={e => { setResultFilter(e.target.value); setPage(0) }} className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none">
          <option value="all">All Results</option>
          <option value="pending">Pending</option>
          <option value="win">Win</option>
          <option value="loss">Loss</option>
        </select>
        <select value={strategyFilter} onChange={e => { setStrategyFilter(e.target.value); setPage(0) }} className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none">
          <option value="all">All Strategies</option>
          {strategies.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="flex-1" />
        <span className="text-[10px] text-neutral-600 tabular-nums">{filtered.length} trades</span>
      </div>

      {/* Summary bar */}
      <div className="shrink-0 flex items-center gap-6 px-3 py-1.5 border-b border-neutral-800 bg-neutral-950/50">
        <span className="text-[10px] text-neutral-500">Total: <span className="text-neutral-200 tabular-nums">{filtered.length}</span></span>
        <span className="text-[10px] text-neutral-500">Wins: <span className="text-green-500 tabular-nums">{wins}</span></span>
        <span className="text-[10px] text-neutral-500">Losses: <span className="text-red-500 tabular-nums">{losses}</span></span>
        <span className="text-[10px] text-neutral-500">Win Rate: <span className={`tabular-nums font-semibold ${winRate >= 50 ? 'text-green-500' : 'text-amber-400'}`}>{winRate.toFixed(1)}%</span></span>
        <span className="text-[10px] text-neutral-500">PNL: <span className={`tabular-nums font-semibold ${totalPnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>{totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}</span></span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full text-[10px] font-mono min-w-[500px]">
          <thead className="sticky top-0 bg-neutral-950">
            <tr className="border-b border-neutral-800">
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Time</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Market</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Dir</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Size</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Entry</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">PNL</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Result</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Mode</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Strategy</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((t: any) => (
              <tr key={t.id} className="border-b border-neutral-800/40 hover:bg-neutral-900/30">
                <td className="px-2 py-1 text-neutral-600 whitespace-nowrap">
                  {t.timestamp ? new Date(t.timestamp).toLocaleString('en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}
                </td>
                <td className="px-2 py-1 text-neutral-400 truncate max-w-[200px]" title={t.market_question || t.event_slug || t.market_ticker}>
                  {(() => {
                    const display = t.market_question || t.event_slug || t.market_ticker || '—'
                    return display.length > 40 ? `${display.slice(0, 38)}…` : display
                  })()}
                </td>
                <td className={`px-2 py-1 font-bold ${t.direction === 'up' ? 'text-green-400' : 'text-red-400'}`}>
                  {t.direction?.toUpperCase() ?? '—'}
                </td>
                <td className="px-2 py-1 text-neutral-300 text-right tabular-nums">${(t.size ?? 0).toFixed(0)}</td>
                <td className="px-2 py-1 text-neutral-500 text-right tabular-nums">{t.entry_price != null ? `${(t.entry_price * 100).toFixed(1)}c` : '—'}</td>
                <td className={`px-2 py-1 text-right tabular-nums ${(t.pnl ?? 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {t.pnl != null ? `${t.pnl >= 0 ? '+' : ''}$${t.pnl.toFixed(2)}` : '—'}
                </td>
                <td className="px-2 py-1">
                  {t.result === 'win' ? <span className="text-green-500">win</span>
                    : t.result === 'loss' ? <span className="text-red-500">loss</span>
                    : <span className="text-neutral-600">pending</span>}
                </td>
                <td className="px-2 py-1">
                  {t.trading_mode === 'live' ? <span className="text-red-400 text-[9px] uppercase">live</span>
                    : t.trading_mode === 'testnet' ? <span className="text-yellow-400 text-[9px] uppercase">testnet</span>
                    : <span className="text-amber-400 text-[9px] uppercase">paper</span>}
                </td>
                <td className="px-2 py-1 text-neutral-600">{t.strategy ?? '—'}</td>
              </tr>
            ))}
            {paginated.length === 0 && (
              <tr><td colSpan={9} className="px-2 py-6 text-center text-neutral-700">No trades found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="shrink-0 flex items-center justify-center gap-3 py-2 border-t border-neutral-800">
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="px-2 py-0.5 border border-neutral-700 text-neutral-400 text-[10px] disabled:opacity-40 hover:border-neutral-500 transition-colors">Prev</button>
          <span className="text-[10px] text-neutral-600">{page + 1} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="px-2 py-0.5 border border-neutral-700 text-neutral-400 text-[10px] disabled:opacity-40 hover:border-neutral-500 transition-colors">Next</button>
        </div>
      )}
    </div>
  )
}
