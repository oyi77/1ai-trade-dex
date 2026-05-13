import { POLL } from '../../polling'
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { DataTable, ColumnDef, FilterDef } from '../DataTable'
import { useTableQuery } from '../../hooks/useTableQuery'
import {
  fetchCopyTraderStatus,
  fetchCopyTraderPositions,
  fetchCopyLeaderboard,
  createWalletConfig,
  ScoredTrader,
  CopyTraderPosition,
} from '../../api'
import { AdminOnly } from '../AdminOnly'

const leaderboardColumns: ColumnDef<ScoredTrader>[] = [
  {
    key: 'rank',
    label: '#',
    render: () => null,
  },
  {
    key: 'pseudonym',
    label: 'Pseudonym',
    sortable: true,
    render: (row) => <span className="text-neutral-200">{row.pseudonym as string}</span>,
  },
  {
    key: 'wallet',
    label: 'Wallet',
    render: (row) => {
      const w = row.wallet as string
      return (
        <span className="text-neutral-500 tabular-nums">
          {w.slice(0, 8)}...{w.slice(-6)}
        </span>
      )
    },
  },
  {
    key: 'score',
    label: 'Score',
    sortable: true,
    className: 'text-right',
    render: (row) => (
      <span className="text-green-500 tabular-nums">{((row.score as number) ?? 0).toFixed(2)}</span>
    ),
  },
  {
    key: 'profit_30d',
    label: 'Profit 30d',
    sortable: true,
    className: 'text-right',
    render: (row) => {
      const v = (row.profit_30d as number) ?? 0
      return (
        <span className={`tabular-nums ${v >= 0 ? 'text-green-500' : 'text-red-500'}`}>
          {v >= 0 ? '+' : ''}${v.toFixed(0)}
        </span>
      )
    },
  },
  {
    key: 'win_rate',
    label: 'Win %',
    sortable: true,
    className: 'text-right',
    render: (row) => (
      <span className="tabular-nums text-neutral-300">
        {(((row.win_rate as number) ?? 0) * 100).toFixed(1)}%
      </span>
    ),
  },
  {
    key: 'total_trades',
    label: 'Trades',
    sortable: true,
    className: 'text-right',
    render: (row) => (
      <span className="tabular-nums text-neutral-400">{row.total_trades as number}</span>
    ),
  },
  {
    key: 'unique_markets',
    label: 'Markets',
    sortable: true,
    className: 'text-right',
    render: (row) => (
      <span className="tabular-nums text-neutral-400">{row.unique_markets as number}</span>
    ),
  },
  {
    key: 'estimated_bankroll',
    label: 'Bankroll',
    sortable: false,
    className: 'text-right',
    render: (row) => (
      <span className="tabular-nums text-neutral-400">
        ${((row.estimated_bankroll as number) ?? 0).toFixed(0)}
      </span>
    ),
  },
]

const positionColumns: ColumnDef<CopyTraderPosition>[] = [
  {
    key: 'wallet',
    label: 'Wallet',
    render: (row) => {
      const w = row.wallet as string
      return (
        <span className="text-neutral-500 tabular-nums">
          {w.slice(0, 8)}...{w.slice(-6)}
        </span>
      )
    },
  },
  {
    key: 'condition_id',
    label: 'Condition ID',
    render: (row) => {
      const c = row.condition_id as string
      return (
        <span className="text-neutral-500 tabular-nums">
          {c.slice(0, 10)}...
        </span>
      )
    },
  },
  {
    key: 'side',
    label: 'Side',
    render: (row) => {
      const side = row.side as string
      return (
        <span className={`uppercase font-bold ${side === 'YES' ? 'text-green-500' : 'text-red-500'}`}>
          {side}
        </span>
      )
    },
  },
  {
    key: 'size',
    label: 'Size',
    className: 'text-right',
    render: (row) => (
      <span className="tabular-nums text-neutral-300">{((row.size as number) ?? 0).toFixed(2)}</span>
    ),
  },
  {
    key: 'opened_at',
    label: 'Opened',
    className: 'text-right',
    render: (row) => {
      const t = row.opened_at as string | null
      return (
        <span className="tabular-nums text-neutral-500">
          {t
            ? new Date(t).toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
              })
            : '—'}
        </span>
      )
    },
  },
]

const leaderboardFilters: FilterDef[] = [
  { key: 'pseudonym', label: 'Pseudonym', type: 'text', placeholder: 'Search...' },
  { key: 'min_score', label: 'Min Score', type: 'number', placeholder: '0' },
]

export function WhaleTrackerTab() {
  const queryClient = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ['copyTraderStatus'],
    queryFn: fetchCopyTraderStatus,
    refetchInterval: POLL.NORMAL,
  })

  const lbQuery = useTableQuery({
    defaultSort: 'score',
    defaultOrder: 'desc',
    defaultLimit: 50,
  })

  const { data: leaderboard = [], isLoading: lbLoading } = useQuery({
    queryKey: ['copyLeaderboard'],
    queryFn: fetchCopyLeaderboard,
    refetchInterval: POLL.SLOW,
  })

  const { data: positions = [], isLoading: posLoading } = useQuery({
    queryKey: ['copyTraderPositions'],
    queryFn: fetchCopyTraderPositions,
    refetchInterval: POLL.NORMAL,
  })

  const [addAddress, setAddAddress] = useState('')
  const [addPseudonym, setAddPseudonym] = useState('')
  const [addResult, setAddResult] = useState<{ ok: boolean; msg: string } | null>(null)

  const addMutation = useMutation({
    mutationFn: () => createWalletConfig({ address: addAddress.trim(), pseudonym: addPseudonym.trim() || undefined }),
    onSuccess: () => {
      setAddResult({ ok: true, msg: 'Wallet added successfully.' })
      setAddAddress('')
      setAddPseudonym('')
      queryClient.invalidateQueries({ queryKey: ['copyLeaderboard'] })
      queryClient.invalidateQueries({ queryKey: ['copyTraderStatus'] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Failed to add wallet.'
      setAddResult({ ok: false, msg })
    },
  })

  const statusColor =
    status?.status === 'ok'
      ? 'border-green-500/30 bg-green-500/5 text-green-400'
      : status?.status === 'degraded'
      ? 'border-amber-500/30 bg-amber-500/5 text-amber-400'
      : 'border-red-500/30 bg-red-500/5 text-red-400'

  const statusDot =
    status?.status === 'ok'
      ? 'bg-green-500'
      : status?.status === 'degraded'
      ? 'bg-amber-500'
      : 'bg-red-500'

  // ⚡ Bolt: Memoize filtered and sorted leaderboard to prevent expensive sorting on every render
  const filteredLeaderboard = useMemo(() => {
    return leaderboard
      .filter((t) => {
        const pseudonymFilter = lbQuery.state.filters['pseudonym'] ?? ''
        const minScore = parseFloat(lbQuery.state.filters['min_score'] ?? '')
        if (pseudonymFilter && !t.pseudonym.toLowerCase().includes(pseudonymFilter.toLowerCase())) return false
        if (!isNaN(minScore) && t.score < minScore) return false
        return true
      })
      .sort((a, b) => {
        const col = lbQuery.state.sort as keyof ScoredTrader
        const dir = lbQuery.state.order === 'asc' ? 1 : -1
        const av = a[col]
        const bv = b[col]
        if (typeof av === 'string' && typeof bv === 'string') {
          return av.localeCompare(bv) * dir
        }
        return (Number(av) - Number(bv)) * dir
      })
  }, [leaderboard, lbQuery.state.filters, lbQuery.state.sort, lbQuery.state.order])

  const lbPage = lbQuery.currentPage
  const lbLimit = lbQuery.state.limit

  // ⚡ Bolt: Memoize pagination slice
  const lbSlice = useMemo(() => {
    return filteredLeaderboard.slice(lbPage * lbLimit, (lbPage + 1) * lbLimit)
  }, [filteredLeaderboard, lbPage, lbLimit])

  // ⚡ Bolt: Memoize ranking map to prevent recreating objects unnecessarily
  const lbWithRank = useMemo(() => {
    return lbSlice.map((t, i) => ({
      ...t,
      rank: lbPage * lbLimit + i + 1,
    })) as unknown as ScoredTrader[]
  }, [lbSlice, lbPage, lbLimit])

  const leaderboardColumnsWithRank: ColumnDef<ScoredTrader>[] = [
    {
      key: 'rank',
      label: '#',
      render: (row) => (
        <span className="tabular-nums text-neutral-600">{(row as unknown as Record<string, unknown>)['rank'] as number}</span>
      ),
    },
    ...leaderboardColumns.slice(1),
  ]

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 font-mono">

      {/* Status Banner */}
      {status && (
        <div className={`border px-3 py-2 flex items-center gap-3 ${statusColor}`}>
          <div className={`w-2 h-2 rounded-full shrink-0 ${statusDot}`} />
          <span className="text-[10px] uppercase tracking-wider font-bold">
            Copy Trader: {status.status ?? 'unknown'}
          </span>
          <span className="text-[10px] text-neutral-500">
            {status.tracked_wallets} wallet{status.tracked_wallets !== 1 ? 's' : ''} tracked
          </span>
          {status.errors && status.errors.length > 0 && (
            <div className="ml-auto flex gap-3">
              {status.errors.map((e, i) => (
                <span key={i} className="text-[9px] text-red-400 tabular-nums">
                  [{e.source}] {e.message}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Leaderboard */}
      <div className="border border-neutral-800">
        <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
          <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Whale Leaderboard</span>
          <span className="text-[10px] text-neutral-600 tabular-nums">{filteredLeaderboard.length}</span>
        </div>
        <div className="p-3">
          <DataTable<ScoredTrader>
            columns={leaderboardColumnsWithRank}
            rows={lbWithRank}
            total={filteredLeaderboard.length}
            sort={lbQuery.state.sort}
            order={lbQuery.state.order}
            limit={lbLimit}
            currentPage={lbPage}
            onSort={lbQuery.setSort}
            onPageChange={lbQuery.setPage}
            filters={leaderboardFilters}
            filterValues={lbQuery.state.filters}
            onFilterChange={lbQuery.setFilter}
            loading={lbLoading}
            emptyMessage="No leaderboard data"
            keyField="wallet"
          />
        </div>
      </div>

      <AdminOnly fallback={<div className="border border-neutral-800 px-3 py-2 text-[10px] text-neutral-600 uppercase tracking-wider">Wallet tracking controls are admin-only.</div>}>
      <div className="border border-neutral-800">
        <div className="px-3 py-2 border-b border-neutral-800">
          <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Track Wallet</span>
        </div>
        <div className="p-3">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] text-neutral-600 uppercase tracking-wider">Address</span>
              <input
                type="text"
                value={addAddress}
                onChange={(e) => { setAddAddress(e.target.value); setAddResult(null) }}
                placeholder="0x..."
                className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:border-neutral-500 focus:outline-none w-64"
              />
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-[9px] text-neutral-600 uppercase tracking-wider">Pseudonym</span>
              <input
                type="text"
                value={addPseudonym}
                onChange={(e) => { setAddPseudonym(e.target.value); setAddResult(null) }}
                placeholder="Optional label"
                className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-[10px] px-2 py-0.5 font-mono focus:border-neutral-500 focus:outline-none w-40"
              />
            </div>
            <button
              onClick={() => addMutation.mutate()}
              disabled={!addAddress.trim() || addMutation.isPending}
              className="px-3 py-0.5 text-[10px] border border-green-700 text-green-400 hover:bg-green-500/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors uppercase tracking-wider"
            >
              {addMutation.isPending ? 'Adding...' : 'Track Wallet'}
            </button>
            {addResult && (
              <span className={`text-[10px] ${addResult.ok ? 'text-green-500' : 'text-red-500'}`}>
                {addResult.msg}
              </span>
            )}
          </div>
        </div>
      </div>
      </AdminOnly>

      {/* Active Positions */}
      <div className="border border-neutral-800">
        <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
          <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Active Positions</span>
          <span className="text-[10px] text-neutral-600 tabular-nums">{positions.length}</span>
        </div>
        <div className="p-3">
          <DataTable<CopyTraderPosition>
            columns={positionColumns}
            rows={positions as unknown as CopyTraderPosition[]}
            total={positions.length}
            loading={posLoading}
            emptyMessage="No active positions"
            keyField="condition_id"
          />
        </div>
      </div>

    </div>
  )
}
