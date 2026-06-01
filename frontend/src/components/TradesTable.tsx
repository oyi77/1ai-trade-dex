import { formatDistanceToNow } from 'date-fns'
import { ArrowUpDown, ArrowUp, ArrowDown, Filter } from 'lucide-react'
import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Trade } from '../types'
import { platformStyles } from '../utils'

interface Props {
  trades: Trade[]
}

type SortKey = 'timestamp' | 'size' | 'pnl' | 'result'
type SortDir = 'asc' | 'desc'
type FilterType = 'all' | 'settled' | 'wins' | 'losses' | 'pending'

export function TradesTable({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('timestamp')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [filter, setFilter] = useState<FilterType>('all')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const filteredTrades = useMemo(() => {
    switch (filter) {
      case 'settled':
        return trades.filter(t => t.settled && t.result !== 'expired')
      case 'wins':
        return trades.filter(t => t.result === 'win')
      case 'losses':
        return trades.filter(t => t.result === 'loss')
      case 'pending':
        return trades.filter(t => t.result === 'pending')
      default:
        return trades
    }
  }, [trades, filter])

  const sortedTrades = useMemo(() => {
    return [...filteredTrades].sort((a, b) => {
      let aVal: number | string, bVal: number | string
      switch (sortKey) {
        case 'timestamp':
          aVal = new Date(a.timestamp).getTime()
          bVal = new Date(b.timestamp).getTime()
          break
        case 'size':
          aVal = a.size; bVal = b.size; break
        case 'pnl':
          aVal = a.pnl ?? 0; bVal = b.pnl ?? 0; break
        case 'result':
          aVal = a.result; bVal = b.result; break
        default: return 0
      }
      if (typeof aVal === 'string') {
        return sortDir === 'asc'
          ? aVal.localeCompare(bVal as string)
          : (bVal as string).localeCompare(aVal)
      }
      return sortDir === 'asc' ? aVal - (bVal as number) : (bVal as number) - aVal
    })
  }, [filteredTrades, sortKey, sortDir])

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return <ArrowUpDown className="w-2.5 h-2.5 text-neutral-600" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-2.5 h-2.5 text-amber-500" />
      : <ArrowDown className="w-2.5 h-2.5 text-amber-500" />
  }

  // ⚡ Bolt: Memoized filter counts with a single O(N) loop to prevent O(N*4) recalculations on every render
  const filterButtons = useMemo(() => {
    let wins = 0, losses = 0, pending = 0, settled = 0;
    for (let i = 0; i < trades.length; i++) {
      const t = trades[i];
      if (t.result === 'win') wins++;
      else if (t.result === 'loss') losses++;
      else if (t.result === 'pending') pending++;

      if (t.settled && t.result !== 'expired') settled++;
    }

    return [
      { key: 'all' as FilterType, label: 'All', count: trades.length },
      { key: 'wins' as FilterType, label: 'Wins', count: wins },
      { key: 'losses' as FilterType, label: 'Losses', count: losses },
      { key: 'pending' as FilterType, label: 'Pending', count: pending },
      { key: 'settled' as FilterType, label: 'Settled', count: settled },
    ]
  }, [trades]);

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-neutral-600">
        <p className="text-xs">No trades yet</p>
        <p className="text-[10px] mt-0.5">Trades will appear here</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-neutral-800 bg-neutral-950">
        <Filter className="w-3 h-3 text-neutral-600" />
        {filterButtons.map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
              filter === key
                ? key === 'wins' ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                : key === 'losses' ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                : 'text-neutral-500 hover:text-neutral-300 border border-transparent'
            }`}
          >
            {label} ({count})
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-auto">
        <table className="w-full">
      <thead className="sticky top-0 bg-neutral-950 z-10">
        <tr className="text-neutral-600 text-left text-[10px] border-b border-neutral-800">
          <th className="py-1.5 px-1.5 font-medium w-5"></th>
          <th
            className="py-1.5 px-1.5 font-medium cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('result')}
          >
            <div className="flex items-center gap-0.5">
              St <SortIcon column="result" />
            </div>
          </th>
          <th className="py-1.5 px-1.5 font-medium">Market</th>
          <th className="py-1.5 px-1.5 font-medium">Strategy</th>
          <th className="py-1.5 px-1.5 font-medium text-right">Conf</th>
          <th className="py-1.5 px-1.5 font-medium text-center">Dir</th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('size')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Size <SortIcon column="size" />
            </div>
          </th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('pnl')}
          >
            <div className="flex items-center justify-end gap-0.5">
              P&L <SortIcon column="pnl" />
            </div>
          </th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('timestamp')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Time <SortIcon column="timestamp" />
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        <AnimatePresence>
          {sortedTrades.map((trade, i) => {
            const isPending = trade.result === 'pending'
            const isWin = trade.result === 'win'
            const isLoss = trade.result === 'loss'
            const isExpired = trade.result === 'expired'
            const isUp = trade.direction === 'up'
            const style = platformStyles[trade.platform?.toLowerCase()]

            const rowBg = isWin 
              ? 'bg-green-500/10 hover:bg-green-500/20 border-l-2 border-l-green-500' 
              : isLoss 
              ? 'bg-red-500/10 hover:bg-red-500/20 border-l-2 border-l-red-500'
              : 'hover:bg-neutral-800/30'

            return (
              <motion.tr
                key={trade.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.02 }}
                className={`border-b border-neutral-800/50 text-[11px] ${rowBg}`}
              >
                <td className="py-1 px-1.5">
                  {style && (
                    <span className={`platform-badge ${style.badge}`}>
                      {style.icon}
                    </span>
                  )}
                </td>
                <td className="py-1 px-1.5">
                  <span className={`text-[9px] font-medium uppercase ${
                    isPending ? 'text-amber-500' 
                    : isWin ? 'text-green-500' 
                    : isLoss ? 'text-red-500'
                    : isExpired ? 'text-neutral-500'
                    : 'text-neutral-500'
                  }`}>
                    {isPending ? 'PND' : isWin ? 'WIN' : isLoss ? 'LOSS' : isExpired ? 'EXP' : trade.result?.toUpperCase() || '-'}
                  </span>
                </td>
                <td className="py-1 px-1.5">
                  <span className="text-neutral-400 truncate block max-w-[200px]" title={trade.market_question || trade.event_slug || trade.market_ticker || ''}>
                    {(trade.market_question || trade.event_slug || trade.market_ticker || '').replace('btc-updown-5m-', '')}
                  </span>
                  {trade.signal_source && (
                    <span className="text-[9px] text-neutral-600 block truncate max-w-[100px]">{trade.signal_source}</span>
                  )}
                </td>
                <td className="py-1 px-1.5">
                  {trade.strategy ? (
                    <span className="text-[9px] bg-neutral-800 px-1 rounded text-neutral-400 whitespace-nowrap">{trade.strategy}</span>
                  ) : (
                    <span className="text-neutral-700">-</span>
                  )}
                </td>
                <td className="py-1 px-1.5 text-right text-neutral-500 tabular-nums">
                  {trade.confidence != null ? `${Math.round(trade.confidence * 100)}%` : <span className="text-neutral-700">-</span>}
                </td>
                <td className="py-1 px-1.5 text-center">
                  <span className={`text-[10px] font-semibold uppercase ${isUp ? 'text-green-500' : 'text-red-500'}`}>
                    {trade.direction}
                  </span>
                </td>
                  <td className="py-1 px-1.5 text-right text-neutral-300 tabular-nums">
                  ${(trade.size ?? 0).toFixed(0)}
                </td>
                <td className="py-1 px-1.5 text-right">
                  {trade.pnl != null ? (
                    <span className={`font-semibold tabular-nums ${
                      trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'
                    }`}>
                      {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-neutral-600">-</span>
                  )}
                </td>
                <td className="py-1 px-1.5 text-right text-[10px] text-neutral-600 tabular-nums">
                  {formatDistanceToNow(new Date(trade.timestamp), { addSuffix: false })}
                </td>
              </motion.tr>
            )
          })}
        </AnimatePresence>
      </tbody>
        </table>
      </div>
    </div>
  )
}
