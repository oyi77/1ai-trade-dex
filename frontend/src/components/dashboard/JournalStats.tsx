import type { JournalStats } from '../../types'

interface JournalStatsProps {
  stats: JournalStats | null
  loading: boolean
}

export function JournalStatsCards({ stats, loading }: JournalStatsProps) {
  if (loading) {
    return (
      <div className="flex items-center gap-3 px-3 py-2 border-b border-neutral-800 bg-neutral-950">
        <span className="text-[10px] text-neutral-600 uppercase tracking-wider">Loading stats...</span>
      </div>
    )
  }

  if (!stats) return null

  const strategies = Object.entries(stats.by_strategy ?? {})

  return (
    <div className="border-b border-neutral-800 bg-neutral-950">
      {/* Stat cards row */}
      <div className="flex items-center gap-6 px-3 py-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-neutral-600 uppercase">Trades</span>
          <span className="text-sm font-semibold tabular-nums text-neutral-100">{stats.total_trades}</span>
        </div>

        <div className="w-px h-3 bg-neutral-800" />

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-neutral-600 uppercase">P&L</span>
          <span className={`text-sm font-semibold tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            {stats.total_pnl >= 0 ? '+' : '-'}${Math.abs(stats.total_pnl).toFixed(2)}
          </span>
        </div>

        <div className="w-px h-3 bg-neutral-800" />

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-neutral-600 uppercase">Win Rate</span>
          <span className={`text-sm font-semibold tabular-nums ${stats.win_rate >= 0.55 ? 'text-green-500' : stats.win_rate >= 0.45 ? 'text-yellow-500' : 'text-red-500'}`}>
            {(stats.win_rate * 100).toFixed(1)}%
          </span>
        </div>

        <div className="w-px h-3 bg-neutral-800" />

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-neutral-600 uppercase">Avg Edge</span>
          <span className="text-sm font-semibold tabular-nums text-neutral-100">
            {(stats.avg_edge * 100).toFixed(2)}%
          </span>
        </div>
      </div>

      {/* Per-strategy mini table */}
      {strategies.length > 0 && (
        <div className="px-3 pb-2">
          <table className="w-full text-[9px] font-mono">
            <thead>
              <tr className="border-b border-neutral-800/60">
                <th className="text-left px-1 py-0.5 text-neutral-600 uppercase tracking-wider">Strategy</th>
                <th className="text-right px-1 py-0.5 text-neutral-600 uppercase tracking-wider">Trades</th>
                <th className="text-right px-1 py-0.5 text-neutral-600 uppercase tracking-wider">P&L</th>
                <th className="text-right px-1 py-0.5 text-neutral-600 uppercase tracking-wider">Win Rate</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map(([name, s]) => (
                <tr key={name} className="border-b border-neutral-800/30">
                  <td className="px-1 py-0.5 text-neutral-400">{name}</td>
                  <td className="px-1 py-0.5 text-right text-neutral-300 tabular-nums">{s.trades}</td>
                  <td className={`px-1 py-0.5 text-right tabular-nums ${s.pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                    {s.pnl >= 0 ? '+' : ''}${s.pnl.toFixed(2)}
                  </td>
                  <td className={`px-1 py-0.5 text-right tabular-nums ${s.win_rate >= 0.55 ? 'text-green-500' : s.win_rate >= 0.45 ? 'text-yellow-500' : 'text-red-500'}`}>
                    {(s.win_rate * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
