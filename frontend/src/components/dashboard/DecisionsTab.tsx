import { POLL } from '../../polling'
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchDecisions } from '../../api'
import type { DecisionLogRow } from '../../api'

export function DecisionsTab() {
  const [stratFilter, setStratFilter] = useState<string>('all')
  const [decisionFilter, setDecisionFilter] = useState<string>('all')

  const { data, isLoading, error } = useQuery({
    queryKey: ['decisions-tab'],
    queryFn: () => fetchDecisions({ limit: 100 }),
    refetchInterval: POLL.NORMAL,
  })

  const rows: DecisionLogRow[] = useMemo(() => data?.items ?? [], [data?.items])

  // Bolt: Memoize strategy extraction to avoid O(N) array iteration and Set creation on every render
  const strategies = useMemo(() => {
    return Array.from(new Set(rows.map(r => r.strategy).filter(Boolean)))
  }, [rows])

  // Bolt: Memoize filtered rows to prevent expensive O(N) re-filtering on rapid real-time updates
  const filtered = useMemo(() => {
    return rows.filter(r => {
      if (stratFilter !== 'all' && r.strategy !== stratFilter) return false
      if (decisionFilter !== 'all' && r.decision !== decisionFilter) return false
      return true
    })
  }, [rows, stratFilter, decisionFilter])

  if (isLoading) return <div className="flex items-center justify-center h-64 text-neutral-500 text-sm">Loading...</div>
  if (error) return <div className="flex items-center justify-center h-64 text-red-500/60 text-sm">Failed to load data</div>

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 flex items-center gap-3 px-3 py-2 border-b border-neutral-800 bg-neutral-950">
        <span className="text-[9px] text-neutral-600 uppercase tracking-wider">Filters</span>
        <select value={stratFilter} onChange={e => setStratFilter(e.target.value)} className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none">
          <option value="all">All Strategies</option>
          {strategies.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={decisionFilter} onChange={e => setDecisionFilter(e.target.value)} className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none">
          <option value="all">All Decisions</option>
          <option value="BUY">BUY</option>
          <option value="SKIP">SKIP</option>
          <option value="SELL">SELL</option>
          <option value="HOLD">HOLD</option>
        </select>
        <div className="flex-1" />
        <span className="text-[10px] text-neutral-600 tabular-nums">{filtered.length} decisions</span>
      </div>
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full text-[10px] font-mono min-w-[500px]">
          <thead className="sticky top-0 bg-neutral-950">
            <tr className="border-b border-neutral-800">
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Time</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Strategy</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Market</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Decision</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Conf</th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Reason</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r: DecisionLogRow) => (
              <tr key={r.id} className="border-b border-neutral-800/40 hover:bg-neutral-900/30">
                <td className="px-2 py-1 text-neutral-600 whitespace-nowrap">
                  {r.created_at ? new Date(r.created_at).toLocaleString('en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}
                </td>
                <td className="px-2 py-1 text-neutral-500">{r.strategy}</td>
                <td className="px-2 py-1 text-neutral-400 truncate max-w-[80px]" title={r.market_ticker ?? ''}>
                  {(r.market_ticker ?? '').length > 14 ? `${(r.market_ticker ?? '').slice(0, 12)}…` : (r.market_ticker ?? '—')}
                </td>
                <td className="px-2 py-1">
                  {r.decision === 'BUY' ? <span className="text-green-400 font-bold">BUY</span>
                    : r.decision === 'SKIP' ? <span className="text-neutral-500">SKIP</span>
                    : r.decision === 'SELL' ? <span className="text-red-400 font-bold">SELL</span>
                    : <span className="text-neutral-400">{r.decision}</span>}
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-neutral-500">
                  {r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : '—'}
                </td>
                <td className="px-2 py-1 text-neutral-600 truncate max-w-[200px]" title={r.reason ?? ''}>
                  {r.reason ?? '—'}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={6} className="px-2 py-6 text-center text-neutral-700">No decisions found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
