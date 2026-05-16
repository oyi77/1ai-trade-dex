import { motion } from 'framer-motion'
import { useMemo } from 'react'

interface Trade {
  id: string | number
  market_ticker: string
  market_question?: string
  direction: string
  entry_price: number
  exit_price?: number | null
  pnl: number | null
  timestamp: string
  trading_mode?: string
}

interface WinningTradesPreviewProps {
  trades: Trade[]
  title?: string
  variant?: 'winners' | 'losses'
  onViewAll?: () => void
}

export function WinningTradesPreview({
  trades,
  title = 'Top Winning Trades',
  variant = 'winners',
  onViewAll,
}: WinningTradesPreviewProps) {
  const isLosses = variant === 'losses'

  // ⚡ Bolt: Memoize expensive filter and sort operations to prevent UI thread blocking
  const topTrades = useMemo(() => {
    return trades
      .filter(t => isLosses ? (t.pnl ?? 0) < 0 : (t.pnl ?? 0) > 0)
      .sort((a, b) => isLosses ? (a.pnl ?? 0) - (b.pnl ?? 0) : (b.pnl ?? 0) - (a.pnl ?? 0))
      .slice(0, 5)
  }, [trades, isLosses])

  if (topTrades.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="text-xs text-neutral-600">No {isLosses ? 'loss' : 'winning'} trades yet</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between shrink-0">
        <span className="text-[10px] text-neutral-500 uppercase tracking-wider">{title}</span>
        {onViewAll && (
          <button
            onClick={onViewAll}
            className={`text-[9px] uppercase tracking-wider transition-colors ${isLosses ? 'text-red-500 hover:text-red-400' : 'text-green-500 hover:text-green-400'}`}
          >
            View All →
          </button>
        )}
      </div>
      <div className="flex-1 overflow-auto">
        <table className="w-full text-[10px] font-mono min-w-[400px]">
          <thead className="sticky top-0 bg-neutral-950">
            <tr className="border-b border-neutral-800">
              <th className="px-3 py-1.5 text-left text-neutral-600 uppercase tracking-wider font-normal">Market</th>
              <th className="px-3 py-1.5 text-left text-neutral-600 uppercase tracking-wider font-normal">Dir</th>
              <th className="px-3 py-1.5 text-right text-neutral-600 uppercase tracking-wider font-normal">Entry</th>
              <th className="px-3 py-1.5 text-right text-neutral-600 uppercase tracking-wider font-normal">Exit</th>
              <th className="px-3 py-1.5 text-right text-neutral-600 uppercase tracking-wider font-normal">PNL</th>
              <th className="px-3 py-1.5 text-left text-neutral-600 uppercase tracking-wider font-normal">Mode</th>
            </tr>
          </thead>
          <tbody>
            {topTrades.map((trade, idx) => (
              <motion.tr
                key={trade.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                className="border-b border-neutral-800/40 hover:bg-neutral-900/30 transition-colors"
              >
                <td className="px-3 py-2 text-neutral-400 truncate max-w-[200px]" title={trade.market_question || trade.market_ticker}>
                  {(() => {
                    const display = trade.market_question || trade.market_ticker
                    return display.length > 30 ? `${display.slice(0, 28)}...` : display
                  })()}
                </td>
                <td className="px-3 py-2">
                  <span className={`font-bold ${trade.direction === 'up' ? 'text-green-400' : 'text-red-400'}`}>
                    {trade.direction === 'up' ? '↑' : '↓'}
                  </span>
                </td>
                <td className="px-3 py-2 text-right text-neutral-500 tabular-nums">
                  {(trade.entry_price * 100).toFixed(1)}¢
                </td>
                <td className="px-3 py-2 text-right text-neutral-500 tabular-nums">
                  {trade.exit_price != null ? `${(trade.exit_price * 100).toFixed(1)}¢` : '—'}
                </td>
                <td className={`px-3 py-2 text-right font-semibold tabular-nums ${isLosses ? 'text-red-500' : 'text-green-500'}`}>
                  {(trade.pnl ?? 0) >= 0 ? '+' : '-'}${Math.abs(trade.pnl ?? 0).toFixed(2)}
                </td>
                <td className="px-3 py-2 text-neutral-600 uppercase text-[9px]">
                  {trade.trading_mode ?? '—'}
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
