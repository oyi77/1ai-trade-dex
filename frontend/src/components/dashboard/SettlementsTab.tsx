import { POLL } from '../../polling'
import { ReactNode, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { DataTable, type ColumnDef } from '../DataTable'
import { fetchSettlements } from '../../api'
import { useModeFilter } from '../../hooks/useModeFilter'

interface SettlementRow extends Record<string, unknown> {
  id: number
  trade_id: number
  market_ticker: string
  resolved_outcome: string | null
  pnl: number | null
  settled_at: string | null
  source: string
}

export function SettlementsTab() {
  const { selectedMode } = useModeFilter()
  const { data: settlements, isLoading, isError } = useQuery({
    queryKey: ['settlements'],
    queryFn: () => fetchSettlements(100, 0),
    refetchInterval: POLL.SLOW,
  })

  // Bolt: Memoize filtered settlements to prevent expensive O(N) re-filtering on rapid real-time updates
  const filtered = useMemo(() => {
    return (settlements as SettlementRow[] ?? []).filter((item: any) =>
      selectedMode === 'all' || item.trading_mode === selectedMode
    )
  }, [settlements, selectedMode])

  const columns: ColumnDef<SettlementRow>[] = [
    {
      key: 'settled_at',
      label: 'Time',
      render: (_, value) => {
        if (!value) return '—'
        return new Date(String(value)).toLocaleString('en-US', {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        })
      },
      className: 'tabular-nums text-neutral-500',
    },
    {
      key: 'market_ticker',
      label: 'Market',
      className: 'font-mono max-w-[200px] truncate',
    },
    {
      key: 'resolved_outcome',
      label: 'Outcome',
      render: (_, value): ReactNode => {
        return (value ?? '—') as unknown as ReactNode
      },
    },
    {
      key: 'pnl',
      label: 'PNL',
      render: (_, value) => {
        if (value == null) return '—'
        const num = Number(value)
        return <span className={num >= 0 ? 'text-green-500' : 'text-red-500'}>{num > 0 ? '+' : ''}${num.toFixed(2)}</span>
      },
      className: 'text-right tabular-nums font-semibold',
    },
    {
      key: 'source',
      label: 'Source',
      className: 'text-right uppercase tracking-wider',
    },
  ]

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-4 font-mono">
      <div className="border border-neutral-800">
        <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
          <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Settlement History</span>
          <span className="text-[10px] text-neutral-600 tabular-nums">
            {isLoading || isError ? 0 : (settlements?.length ?? 0)} records
          </span>
        </div>

        <div className="px-3 py-2">
          {isLoading ? (
            <div className="flex items-center justify-center h-32 text-[10px] text-neutral-500">Loading...</div>
          ) : isError ? (
            <div className="flex items-center justify-center h-32 text-[10px] text-red-500/60">Failed to load settlements</div>
          ) : (
            <DataTable<SettlementRow>
              columns={columns}
              rows={filtered}
              total={filtered.length}
              loading={false}
              emptyMessage="No settlements yet — trades settle after market resolution"
              keyField="id"
            />
          )}
        </div>
      </div>
    </div>
  )
}
