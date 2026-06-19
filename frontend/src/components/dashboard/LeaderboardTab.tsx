import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchCopyLeaderboard, createWalletConfig } from '../../api'
import { useModeFilter } from '../../hooks/useModeFilter'
import type { ScoredTrader } from '../../api'

type SortField = 'score' | 'profit_30d' | 'win_rate' | 'total_trades' | 'unique_markets'

export function LeaderboardTab() {
  const { selectedMode } = useModeFilter()
  const { data: leaders = [], isError, isLoading } = useQuery({
    queryKey: ['copy-leaderboard-tab'],
    queryFn: fetchCopyLeaderboard,
    retry: 1,
    staleTime: 60_000,
  })

  const queryClient = useQueryClient()
  const [copyingWallet, setCopyingWallet] = useState<string | null>(null)
  const [copySuccess, setCopySuccess] = useState<string | null>(null)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<SortField>('score')
  const [sortAsc, setSortAsc] = useState(false)
  const [minProfit, setMinProfit] = useState<string>('')
  const [minWinRate, setMinWinRate] = useState<string>('')
  const [minTrades, setMinTrades] = useState<string>('')

  const filtered = useMemo(() => {
    let result = [...leaders]

    if (selectedMode !== 'all') {
      result = result.filter((item: any) => item.trading_mode === selectedMode)
    }

    // Search
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(t =>
        t.wallet?.toLowerCase().includes(q) ||
        (t.pseudonym && t.pseudonym.toLowerCase().includes(q))
      )
    }

    // Filters
    const profitThreshold = minProfit ? parseFloat(minProfit) : null
    if (profitThreshold != null) result = result.filter(t => (t.profit_30d ?? 0) >= profitThreshold)

    const wrThreshold = minWinRate ? parseFloat(minWinRate) / 100 : null
    if (wrThreshold != null) result = result.filter(t => (t.win_rate ?? 0) >= wrThreshold)

    const tradeThreshold = minTrades ? parseInt(minTrades) : null
    if (tradeThreshold != null) result = result.filter(t => (t.total_trades ?? 0) >= tradeThreshold)

    // Sort
    result.sort((a, b) => {
      const av = a[sortBy] ?? 0
      const bv = b[sortBy] ?? 0
      return sortAsc ? av - bv : bv - av
    })

    return result
  }, [leaders, selectedMode, search, sortBy, sortAsc, minProfit, minWinRate, minTrades])

  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortAsc(!sortAsc)
    } else {
      setSortBy(field)
      setSortAsc(false)
    }
  }

  const sortIcon = (field: SortField) => {
    if (sortBy !== field) return ''
    return sortAsc ? ' \u25B2' : ' \u25BC'
  }

  const handleCopyTrade = async (trader: ScoredTrader) => {
    setCopyingWallet(trader.wallet)
    setCopySuccess(null)
    setCopyError(null)
    try {
      await createWalletConfig({
        address: trader.wallet,
        pseudonym: trader.pseudonym || undefined,
        source: 'leaderboard',
        enabled: true,
      })
      setCopySuccess(trader.wallet)
      queryClient.invalidateQueries({ queryKey: ['copy-trader-status'] })
      queryClient.invalidateQueries({ queryKey: ['wallets-config'] })
      setTimeout(() => setCopySuccess(null), 3000)
    } catch {
      setCopyError(trader.wallet)
      setTimeout(() => setCopyError(null), 3000)
    } finally {
      setCopyingWallet(null)
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="shrink-0 px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
        <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Polymarket Leaderboard</span>
        <span className="text-[10px] text-neutral-600 tabular-nums">
          {filtered.length}{filtered.length !== leaders.length ? ` / ${leaders.length}` : ''} traders
        </span>
      </div>

      {isError && (
        <div className="px-3 py-2 text-[10px] text-amber-600/70 border-b border-neutral-800">
          Auth required — log in as admin to view leaderboard
        </div>
      )}

      {/* Search + Filters */}
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-neutral-800 bg-neutral-950 flex-wrap">
        <input
          type="text"
          placeholder="Search wallet or name..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-1 font-mono focus:outline-none focus:border-neutral-500 w-44"
        />
        <div className="flex items-center gap-1">
          <span className="text-[9px] text-neutral-600">Profit &ge;</span>
          <input
            type="number"
            placeholder="$"
            value={minProfit}
            onChange={e => setMinProfit(e.target.value)}
            className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-1.5 py-1 font-mono focus:outline-none w-16"
          />
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[9px] text-neutral-600">WR &ge;</span>
          <input
            type="number"
            placeholder="%"
            value={minWinRate}
            onChange={e => setMinWinRate(e.target.value)}
            className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-1.5 py-1 font-mono focus:outline-none w-14"
          />
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[9px] text-neutral-600">Trades &ge;</span>
          <input
            type="number"
            placeholder="#"
            value={minTrades}
            onChange={e => setMinTrades(e.target.value)}
            className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-1.5 py-1 font-mono focus:outline-none w-14"
          />
        </div>
        {(search || minProfit || minWinRate || minTrades) && (
          <button
            onClick={() => { setSearch(''); setMinProfit(''); setMinWinRate(''); setMinTrades('') }}
            className="text-[9px] px-2 py-1 text-neutral-500 hover:text-neutral-300 border border-neutral-700 hover:border-neutral-500 transition-colors"
          >
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto min-h-0">
        {isLoading ? (
          <div className="px-3 py-12 text-center text-neutral-700 text-[10px]">Loading leaderboard...</div>
        ) : (
          <table className="w-full text-[10px] font-mono min-w-[400px]">
            <thead className="sticky top-0 bg-neutral-950">
              <tr className="border-b border-neutral-800">
                <th className="text-left px-3 py-1.5 text-neutral-600 uppercase tracking-wider w-10">#</th>
                <th className="text-left px-3 py-1.5 text-neutral-600 uppercase tracking-wider">Trader</th>
                <th
                  className="text-right px-3 py-1.5 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400 select-none"
                  onClick={() => handleSort('profit_30d')}
                >
                  Profit{sortIcon('profit_30d')}
                </th>
                <th
                  className="text-right px-3 py-1.5 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400 select-none"
                  onClick={() => handleSort('win_rate')}
                >
                  Win Rate{sortIcon('win_rate')}
                </th>
                <th
                  className="text-right px-3 py-1.5 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400 select-none"
                  onClick={() => handleSort('total_trades')}
                >
                  Trades{sortIcon('total_trades')}
                </th>
                <th
                  className="text-right px-3 py-1.5 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400 select-none"
                  onClick={() => handleSort('unique_markets')}
                >
                  Markets{sortIcon('unique_markets')}
                </th>
                <th
                  className="text-right px-3 py-1.5 text-neutral-600 uppercase tracking-wider cursor-pointer hover:text-neutral-400 select-none"
                  onClick={() => handleSort('score')}
                >
                  Score{sortIcon('score')}
                </th>
                <th className="text-center px-3 py-1.5 text-neutral-600 uppercase tracking-wider">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t: ScoredTrader, i: number) => (
                <tr key={t.wallet} className="border-b border-neutral-800/40 hover:bg-neutral-900/30" title={t.wallet}>
                  <td className="px-3 py-1.5 text-neutral-600 tabular-nums">#{i + 1}</td>
                  <td className="px-3 py-1.5 text-neutral-300">
                    {t.pseudonym || `${t.wallet.slice(0, 6)}...${t.wallet.slice(-4)}`}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums font-semibold ${(t.profit_30d ?? 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    {(t.profit_30d ?? 0) >= 0 ? '+' : ''}${Math.abs(t.profit_30d ?? 0) >= 1000 ? `${((t.profit_30d ?? 0) / 1000).toFixed(1)}k` : (t.profit_30d ?? 0).toFixed(0)}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${(t.win_rate ?? 0) >= 0.6 ? 'text-green-400' : (t.win_rate ?? 0) >= 0.5 ? 'text-neutral-300' : 'text-red-400'}`}>
                    {((t.win_rate ?? 0) * 100).toFixed(1)}%
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-neutral-500">{(t.total_trades ?? 0).toLocaleString()}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-neutral-500">{t.unique_markets}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-amber-400 font-semibold">{(t.score ?? 0).toFixed(2)}</td>
                  <td className="px-3 py-1.5 text-center">
                    {copySuccess === t.wallet ? (
                      <span className="text-[9px] text-green-500">Added</span>
                    ) : copyError === t.wallet ? (
                      <span className="text-[9px] text-red-500">Failed</span>
                    ) : (
                      <button
                        onClick={() => handleCopyTrade(t)}
                        disabled={copyingWallet === t.wallet}
                        className="text-[9px] px-2 py-0.5 bg-amber-500/15 hover:bg-amber-500/25 text-amber-400 border border-amber-500/25 disabled:opacity-40 transition-colors"
                      >
                        {copyingWallet === t.wallet ? '...' : 'Copy'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !isError && !isLoading && (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-neutral-700">
                  {leaders.length === 0 ? 'No leaderboard data' : 'No traders match filters'}
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer summary */}
      {filtered.length > 0 && (
        <div className="shrink-0 px-3 py-1.5 border-t border-neutral-800 flex items-center gap-4 text-[9px] text-neutral-600">
          <span>Avg profit: <span className="text-neutral-400 tabular-nums">${(filtered.reduce((s, t) => s + (t.profit_30d ?? 0), 0) / filtered.length).toFixed(0)}</span></span>
          <span>Avg WR: <span className="text-neutral-400 tabular-nums">{(filtered.reduce((s, t) => s + (t.win_rate ?? 0), 0) / filtered.length * 100).toFixed(1)}%</span></span>
          <span>Top score: <span className="text-amber-400 tabular-nums">{filtered.length > 0 ? filtered.reduce((max, t) => Math.max(max, t.score ?? 0), 0).toFixed(2) : '0.00'}</span></span>
        </div>
      )}
    </div>
  )
}
