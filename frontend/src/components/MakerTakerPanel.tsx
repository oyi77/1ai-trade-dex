/**
 * MakerTakerPanel
 * Displays full-history maker vs taker ROI edge differential with an AGI recommendation badge.
 * Data is fetched from GET /api/analytics/maker-taker (5-min backend cache).
 */

import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fetchMakerTakerStats, type MakerTakerRoleStats } from '../api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(n: number): string {
  return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(2)}%`
}

function usd(n: number): string {
  return `$${n >= 0 ? '' : '-'}${Math.abs(n).toFixed(2)}`
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface RoleCardProps {
  label: string
  stats: MakerTakerRoleStats
  accent: string   // tailwind text color class
  border: string   // tailwind border color class
  glow: string     // tailwind shadow/ring class
}

function RoleCard({ label, stats, accent, border, glow }: RoleCardProps) {
  const roiPositive = stats.roi >= 0
  return (
    <div className={`flex-1 border ${border} bg-neutral-900/60 backdrop-blur-sm p-4 rounded-sm ${glow} transition-shadow`}>
      {/* Header */}
      <div className={`text-[9px] uppercase tracking-widest font-mono font-bold mb-3 ${accent}`}>
        {label}
      </div>

      {/* Big ROI number */}
      <div className={`text-2xl font-bold tabular-nums mb-1 ${roiPositive ? 'text-green-400' : 'text-red-400'}`}>
        {pct(stats.roi)}
      </div>
      <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-3">ROI (all-time)</div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-xs font-mono tabular-nums text-neutral-200">{stats.count}</div>
          <div className="text-[9px] text-neutral-600 uppercase tracking-wider">Trades</div>
        </div>
        <div>
          <div className={`text-xs font-mono tabular-nums ${stats.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {usd(stats.pnl)}
          </div>
          <div className="text-[9px] text-neutral-600 uppercase tracking-wider">PnL</div>
        </div>
        <div>
          <div className="text-xs font-mono tabular-nums text-neutral-200">{usd(stats.size)}</div>
          <div className="text-[9px] text-neutral-600 uppercase tracking-wider">Volume</div>
        </div>
      </div>
    </div>
  )
}

// ── Recommendation Badge ──────────────────────────────────────────────────────

type Recommendation = 'prefer_maker' | 'reduce_taker' | 'neutral' | 'insufficient_data'

const RECO_CONFIG: Record<Recommendation, { label: string; cls: string; dot: string; desc: string }> = {
  prefer_maker: {
    label: 'PREFER MAKER',
    cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    dot: 'bg-emerald-400',
    desc: 'Maker ROI significantly exceeds taker — AGI is increasing market-making strategy weight.',
  },
  reduce_taker: {
    label: 'REDUCE TAKER',
    cls: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    dot: 'bg-amber-400',
    desc: 'Taker ROI is negative — AGI has throttled aggressive fills and enforced maker-only execution.',
  },
  neutral: {
    label: 'NEUTRAL',
    cls: 'bg-neutral-700/40 text-neutral-400 border-neutral-600/30',
    dot: 'bg-neutral-500',
    desc: 'No significant edge differential detected between maker and taker roles.',
  },
  insufficient_data: {
    label: 'INSUFFICIENT DATA',
    cls: 'bg-neutral-800/40 text-neutral-500 border-neutral-700/30',
    dot: 'bg-neutral-600',
    desc: 'Fewer than 20 settled trades per role. AGI will act once sufficient data is collected.',
  },
}

// ── Main Component ────────────────────────────────────────────────────────────

export function MakerTakerPanel() {
  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ['maker-taker-stats'],
    queryFn: fetchMakerTakerStats,
    refetchInterval: 5 * 60 * 1000,  // 5-minute auto-refresh (matches backend cache TTL)
    staleTime: 4 * 60 * 1000,
  })

  const reco = (data?.recommendation ?? 'insufficient_data') as Recommendation
  const recoCfg = RECO_CONFIG[reco]

  if (isLoading) {
    return (
      <div className="border border-neutral-800 bg-neutral-900/50 p-4 rounded-sm animate-pulse">
        <div className="h-3 w-32 bg-neutral-800 rounded mb-4" />
        <div className="flex gap-3">
          <div className="flex-1 h-28 bg-neutral-800 rounded" />
          <div className="flex-1 h-28 bg-neutral-800 rounded" />
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="border border-neutral-800 bg-neutral-900/50 p-4 rounded-sm">
        <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-1">Maker vs Taker</div>
        <div className="text-xs text-red-400/70">Failed to load — backend may be offline.</div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="border border-neutral-800 bg-neutral-900/50 p-4 rounded-sm"
      id="maker-taker-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[9px] text-neutral-500 uppercase tracking-wider">AGI · Maker vs Taker</div>
          <div className="text-xs text-neutral-200 font-semibold mt-0.5">Execution Role Edge Differential</div>
        </div>
        {/* Recommendation badge */}
        <div className={`flex items-center gap-1.5 px-2 py-1 border rounded-sm text-[9px] font-bold uppercase tracking-wider ${recoCfg.cls}`}>
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${recoCfg.dot}`} />
          {recoCfg.label}
        </div>
      </div>

      {/* Role cards */}
      <div className="flex gap-3 mb-3">
        <RoleCard
          label="Maker"
          stats={data.maker}
          accent="text-cyan-400"
          border="border-cyan-500/20"
          glow="hover:shadow-[0_0_12px_0_rgba(6,182,212,0.12)]"
        />
        <RoleCard
          label="Taker"
          stats={data.taker}
          accent="text-violet-400"
          border="border-violet-500/20"
          glow="hover:shadow-[0_0_12px_0_rgba(139,92,246,0.12)]"
        />
      </div>

      {/* Recommendation description */}
      <div className="text-[9px] text-neutral-500 leading-relaxed border-t border-neutral-800/60 pt-2">
        {recoCfg.desc}
      </div>

      {/* Cache timestamp */}
      {dataUpdatedAt > 0 && (
        <div className="text-[9px] text-neutral-700 font-mono mt-1">
          cached_at: {data.cached_at ? new Date(data.cached_at).toLocaleTimeString() : '—'}
        </div>
      )}
    </motion.div>
  )
}
