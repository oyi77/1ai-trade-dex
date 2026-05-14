import { POLL } from '../../polling'
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchSignalHistory } from '../../api'
import { useModeFilter } from '../../hooks/useModeFilter'
import type { SignalHistoryRow } from '../../api'

export function SignalsTab() {
  const { selectedMode } = useModeFilter()
  const [dirFilter, setDirFilter] = useState<string>('all')
  const [execFilter, setExecFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')

  const { data, isLoading, error } = useQuery({
    queryKey: ['signal-history-tab'],
    queryFn: () => fetchSignalHistory({ limit: 200 }),
    refetchInterval: POLL.SLOW,
  })

  const rows: SignalHistoryRow[] = useMemo(() => data?.items ?? [], [data?.items])
  // Bolt: Memoize filtered rows to prevent expensive O(N) re-filtering on rapid real-time updates
  const filtered = useMemo(() => {
    return rows.filter(r => {
      if (selectedMode !== 'all' && r.trading_mode !== selectedMode) return false
      if (dirFilter !== 'all' && r.direction !== dirFilter) return false
      if (execFilter === 'yes' && !r.executed) return false
      if (execFilter === 'no' && r.executed) return false
      if (typeFilter !== 'all' && (r.market_type ?? 'btc') !== typeFilter) return false
      return true
    })
  }, [rows, selectedMode, dirFilter, execFilter, typeFilter])

  if (isLoading) return <div className="flex items-center justify-center h-64 text-neutral-500 text-sm">Loading...</div>
  if (error) return <div className="flex items-center justify-center h-64 text-red-500/60 text-sm">Failed to load data</div>

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 flex items-center gap-3 px-3 py-2 border-b border-neutral-800 bg-neutral-950">
        <span className="text-[9px] text-neutral-600 uppercase tracking-wider">Filters</span>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none">
          <option value="all">All Types</option>
          <option value="btc">BTC</option>
          <option value="weather">Weather</option>
          <option value="copy">Copy Trader</option>
          <option value="ai">AI</option>
        </select>
        <select value={dirFilter} onChange={e => setDirFilter(e.target.value)} className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none">
          <option value="all">All Directions</option>
          <option value="up">Up</option>
          <option value="down">Down</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
        <select value={execFilter} onChange={e => setExecFilter(e.target.value)} className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none">
          <option value="all">All</option>
          <option value="yes">Executed</option>
          <option value="no">Skipped</option>
        </select>
        <div className="flex-1" />
        <span className="text-[10px] text-neutral-600 tabular-nums">{filtered.length} signals</span>
      </div>
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full text-[10px] font-mono min-w-[500px]">
          <thead className="sticky top-0 bg-neutral-950">
            <tr className="border-b border-neutral-800">
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Time</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Type</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Market</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Dir</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Edge%</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Conf%</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Executed</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(row => (
              <tr key={row.id} className={`border-b border-neutral-800/40 hover:bg-neutral-900/30 ${row.executed ? 'bg-green-500/5' : ''}`}>
                <td className="px-2 py-1 text-neutral-600 whitespace-nowrap">
                  {row.timestamp ? new Date(row.timestamp).toLocaleString('en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}
                </td>
                <td className="px-2 py-1">
                  {row.market_type === 'weather'
                    ? <span className="text-cyan-500">WX</span>
                    : row.market_type === 'copy'
                    ? <span className="text-purple-400">COPY</span>
                    : row.market_type === 'ai'
                    ? <span className="text-amber-400">AI</span>
                    : <span className="text-orange-400">BTC</span>}
                </td>
                <td className="px-2 py-1 text-neutral-400 truncate max-w-[100px]" title={row.market_ticker ?? ''}>
                  {(row.market_ticker ?? '').length > 18 ? `${(row.market_ticker ?? '').slice(0, 16)}…` : (row.market_ticker ?? '—')}
                </td>
                <td className={`px-2 py-1 font-bold ${row.direction === 'up' || row.direction === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
                  {row.direction?.toUpperCase()}
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-neutral-300">
                  {row.edge != null ? `${(row.edge * 100).toFixed(1)}%` : '—'}
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-neutral-500">
                  {row.confidence != null ? `${(row.confidence * 100).toFixed(0)}%` : '—'}
                </td>
                <td className="px-2 py-1">
                  <span className={row.executed ? 'text-green-500' : 'text-neutral-700'}>{row.executed ? 'yes' : 'no'}</span>
                </td>
                <td className="px-2 py-1">
                  {row.outcome_correct == null ? <span className="text-neutral-700">pending</span>
                    : row.outcome_correct ? <span className="text-green-500">win</span>
                    : <span className="text-red-500">loss</span>}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="px-2 py-6 text-center text-neutral-700">No signals found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
