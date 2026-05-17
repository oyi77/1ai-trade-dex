import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { NavBar } from '../components/NavBar'
import { JournalStatsCards } from '../components/dashboard/JournalStats'
import { TradeDetailModal } from '../components/TradeDetailModal'
import { fetchJournal, fetchJournalStats, updateJournalNotes } from '../api'
import type { JournalEntry } from '../types'

export default function TradingJournal() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize] = useState(50)
  const [strategy, setStrategy] = useState('')
  const [mode, setMode] = useState('')
  const [result, setResult] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sortBy, setSortBy] = useState('timestamp')
  const [sortDir, setSortDir] = useState('desc')
  const [selectedEntry, setSelectedEntry] = useState<JournalEntry | null>(null)

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['journal-stats', strategy, mode],
    queryFn: () => fetchJournalStats({
      strategy: strategy || undefined,
      mode: mode || undefined,
    }),
  })

  const { data: journal, isLoading } = useQuery({
    queryKey: ['journal', page, pageSize, strategy, mode, result, dateFrom, dateTo, sortBy, sortDir],
    queryFn: () => fetchJournal({
      page,
      page_size: pageSize,
      strategy: strategy || undefined,
      mode: mode || undefined,
      result: result || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
    }),
  })

  const notesMutation = useMutation({
    mutationFn: ({ tradeId, notes, tags }: { tradeId: number; notes: string; tags: string[] }) =>
      updateJournalNotes(tradeId, notes, tags),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['journal'] })
    },
  })

  const handleSort = useCallback((col: string) => {
    if (sortBy === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(col)
      setSortDir('desc')
    }
    setPage(1)
  }, [sortBy])

  const handleSaveNotes = useCallback((tradeId: number, notes: string, tags: string[]) => {
    notesMutation.mutate({ tradeId, notes, tags })
  }, [notesMutation])

  const handleExportCsv = useCallback(() => {
    const params = new URLSearchParams()
    if (strategy) params.set('strategy', strategy)
    if (mode) params.set('mode', mode)
    if (result) params.set('result', result)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    params.set('export', 'csv')
    window.open(`/api/v1/journal?${params.toString()}`, '_blank')
  }, [strategy, mode, result, dateFrom, dateTo])

  const entries = journal?.entries ?? []
  const total = journal?.total ?? 0
  const totalPages = Math.ceil(total / pageSize)

  const SortIcon = ({ col }: { col: string }) => {
    if (sortBy !== col) return <span className="text-neutral-700 ml-0.5">↕</span>
    return <span className="text-neutral-400 ml-0.5">{sortDir === 'asc' ? '↑' : '↓'}</span>
  }

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      <NavBar title="Trading Journal" />

      {/* Stats */}
      <JournalStatsCards stats={stats ?? null} loading={statsLoading} />

      {/* Filter bar */}
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-neutral-800 bg-neutral-950/50 flex-wrap">
        <select
          value={strategy}
          onChange={e => { setStrategy(e.target.value); setPage(1) }}
          className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none"
        >
          <option value="">All Strategies</option>
          {Object.keys(stats?.by_strategy ?? {}).map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          value={mode}
          onChange={e => { setMode(e.target.value); setPage(1) }}
          className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none"
        >
          <option value="">All Modes</option>
          <option value="paper">Paper</option>
          <option value="testnet">Testnet</option>
          <option value="live">Live</option>
        </select>

        <select
          value={result}
          onChange={e => { setResult(e.target.value); setPage(1) }}
          className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none"
        >
          <option value="">All Results</option>
          <option value="win">Win</option>
          <option value="loss">Loss</option>
          <option value="pending">Pending</option>
        </select>

        <input
          type="date"
          value={dateFrom}
          onChange={e => { setDateFrom(e.target.value); setPage(1) }}
          className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none"
          placeholder="From"
        />
        <input
          type="date"
          value={dateTo}
          onChange={e => { setDateTo(e.target.value); setPage(1) }}
          className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:outline-none"
          placeholder="To"
        />

        <div className="flex-1" />

        <span className="text-[10px] text-neutral-600 tabular-nums">{total} entries</span>

        <button
          onClick={handleExportCsv}
          className="text-[9px] text-neutral-600 hover:text-green-500 uppercase tracking-wider border border-neutral-800 hover:border-green-500/40 px-2 py-0.5 transition-colors"
        >
          Export CSV
        </button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full text-[10px] font-mono min-w-[800px]">
          <thead className="sticky top-0 bg-neutral-950 z-10">
            <tr className="border-b border-neutral-800">
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400" onClick={() => handleSort('timestamp')}>
                Time<SortIcon col="timestamp" />
              </th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400" onClick={() => handleSort('market_ticker')}>
                Market<SortIcon col="market_ticker" />
              </th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400" onClick={() => handleSort('strategy')}>
                Strategy<SortIcon col="strategy" />
              </th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Dir</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Entry</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Size</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400" onClick={() => handleSort('edge')}>
                Edge<SortIcon col="edge" />
              </th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider">Conf</th>
              <th className="text-right px-2 py-1 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400" onClick={() => handleSort('pnl')}>
                P&L<SortIcon col="pnl" />
              </th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400" onClick={() => handleSort('result')}>
                Result<SortIcon col="result" />
              </th>
              <th className="text-left px-2 py-1 text-neutral-600 uppercase tracking-wider">Mode</th>
              <th className="text-center px-2 py-1 text-neutral-600 uppercase tracking-wider">Notes</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={12} className="px-2 py-8 text-center text-neutral-600">Loading...</td></tr>
            ) : entries.length === 0 ? (
              <tr><td colSpan={12} className="px-2 py-8 text-center text-neutral-700">No journal entries found</td></tr>
            ) : (
              entries.map((entry) => {
                const t = entry.trade
                return (
                  <tr
                    key={t.id}
                    className="border-b border-neutral-800/40 hover:bg-neutral-900/30 cursor-pointer"
                    onClick={() => setSelectedEntry(entry)}
                  >
                    <td className="px-2 py-1 text-neutral-600 whitespace-nowrap">
                      {t.timestamp ? new Date(t.timestamp).toLocaleString('en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}
                    </td>
                    <td className="px-2 py-1 text-neutral-400 truncate max-w-[200px]" title={t.market_ticker}>
                      {t.market_ticker?.length > 35 ? `${t.market_ticker.slice(0, 33)}…` : t.market_ticker ?? '—'}
                    </td>
                    <td className="px-2 py-1 text-neutral-500">{t.strategy ?? '—'}</td>
                    <td className={`px-2 py-1 font-bold ${t.direction === 'up' ? 'text-green-400' : 'text-red-400'}`}>
                      {t.direction?.toUpperCase() ?? '—'}
                    </td>
                    <td className="px-2 py-1 text-neutral-500 text-right tabular-nums">
                      {t.entry_price != null ? `${(t.entry_price * 100).toFixed(1)}c` : '—'}
                    </td>
                    <td className="px-2 py-1 text-neutral-300 text-right tabular-nums">
                      ${(t.size ?? 0).toFixed(0)}
                    </td>
                    <td className="px-2 py-1 text-neutral-400 text-right tabular-nums">
                      {t.edge_at_entry != null ? `${(t.edge_at_entry * 100).toFixed(2)}%` : '—'}
                    </td>
                    <td className="px-2 py-1 text-neutral-400 text-right tabular-nums">
                      {t.confidence != null ? `${(t.confidence * 100).toFixed(0)}%` : '—'}
                    </td>
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
                    <td className="px-2 py-1 text-center">
                      {t.journal_notes ? <span className="text-green-500" title={t.journal_notes}>📝</span> : <span className="text-neutral-700">·</span>}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="shrink-0 flex items-center justify-center gap-3 py-2 border-t border-neutral-800">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-2 py-0.5 border border-neutral-700 text-neutral-400 text-[10px] disabled:opacity-40 hover:border-neutral-500 transition-colors"
          >
            Prev
          </button>
          <span className="text-[10px] text-neutral-600">{page} / {totalPages}</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-2 py-0.5 border border-neutral-700 text-neutral-400 text-[10px] disabled:opacity-40 hover:border-neutral-500 transition-colors"
          >
            Next
          </button>
        </div>
      )}

      {/* Detail modal */}
      {selectedEntry && (
        <TradeDetailModal
          entry={selectedEntry}
          onClose={() => setSelectedEntry(null)}
          onSaveNotes={handleSaveNotes}
        />
      )}
    </div>
  )
}
