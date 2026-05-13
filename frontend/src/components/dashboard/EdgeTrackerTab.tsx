import { useCallback, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { fetchEdgePerformance, EdgePerformanceTrack } from '../../api'
import { useModeFilter } from '../../hooks/useModeFilter'

export function EdgeTrackerTab() {
  const { selectedMode } = useModeFilter()
  const [tracks, setTracks] = useState<EdgePerformanceTrack[]>([])
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(7)
  const [error, setError] = useState<string | null>(null)

  const loadEdgePerformance = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchEdgePerformance(days)
      const filtered = data.tracks.filter((track: any) => {
        if (track.track_name === 'legacy') return false
        return selectedMode === 'all' || track.trading_mode === selectedMode
      })
      setTracks(filtered)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load edge performance')
    } finally {
      setLoading(false)
    }
  }, [days, selectedMode])

  useEffect(() => {
    loadEdgePerformance()
  }, [loadEdgePerformance])

  const trackColors: Record<string, string> = {
    realtime: 'bg-blue-700',
    whale: 'bg-purple-700',
    commodity: 'bg-green-700',
  }

  const trackLabels: Record<string, string> = {
    realtime: 'Real-time Scanner',
    whale: 'Whale PNL Tracker',
    commodity: 'Commodity MR',
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-4 font-mono">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white mb-1">Edge Discovery Tracker</h1>
            <p className="text-xs text-neutral-500">Parallel alpha discovery performance metrics</p>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs px-2 py-1"
            >
              <option value={3}>3 Days</option>
              <option value={7}>7 Days</option>
              <option value={14}>14 Days</option>
              <option value={30}>30 Days</option>
            </select>
            <button
              onClick={loadEdgePerformance}
              className="bg-neutral-800 hover:bg-neutral-700 border border-neutral-600 text-white text-xs px-3 py-1"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-900/20 border border-red-700 text-red-400 p-3 mb-4 text-xs">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="text-center py-12">
            <div className="inline-block w-8 h-8 border-2 border-neutral-600 border-t-white animate-spin" />
            <p className="text-neutral-500 text-xs mt-2">Loading edge performance...</p>
          </div>
        )}

        {/* Tracks Grid */}
        {!loading && tracks.length === 0 && (
          <div className="text-center py-12">
            <p className="text-neutral-600 text-xs">No edge tracks found. Start trading to generate performance data.</p>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {tracks.map((track, index) => (
            <motion.div
              key={track.track_name}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="bg-neutral-900 border border-neutral-800 p-4"
            >
              {/* Track Header */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 ${trackColors[track.track_name] || 'bg-neutral-600'}`} />
                  <h3 className="text-sm font-semibold text-white">
                    {trackLabels[track.track_name] || track.track_name}
                  </h3>
                </div>
                <span className={`text-[9px] uppercase tracking-wider px-1.5 py-0.5 ${
                  track.status === 'live' ? 'bg-green-900/50 text-green-400 border border-green-700' :
                  track.status === 'paper' ? 'bg-yellow-900/50 text-yellow-400 border border-yellow-700' :
                  'bg-neutral-800 text-neutral-500 border border-neutral-700'
                }`}>
                  {track.status}
                </span>
              </div>

              {/* Key Metrics */}
              <div className="space-y-2">
                {/* Win Rate */}
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-neutral-500 uppercase">Win Rate</span>
                  <span className={`text-sm font-bold tabular-nums ${
                    (track.win_rate ?? 0) >= 55 ? 'text-green-500' :
                    (track.win_rate ?? 0) >= 45 ? 'text-yellow-500' :
                    'text-red-500'
                  }`}>
                    {((track.win_rate ?? 0) * 100).toFixed(0)}%
                  </span>
                </div>

                {/* PNL */}
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-neutral-500 uppercase">PNL</span>
                  <span className={`text-sm font-bold tabular-nums ${
                    track.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'
                  }`}>
                    {(track.total_pnl ?? 0) >= 0 ? '+' : ''}${Math.abs(track.total_pnl ?? 0).toFixed(0)}
                  </span>
                </div>

                {/* Signals */}
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-neutral-500 uppercase">Signals</span>
                  <span className="text-sm font-semibold text-neutral-300 tabular-nums">
                    {track.signals_executed}/{track.total_signals}
                  </span>
                </div>

                {/* Trades */}
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-neutral-500 uppercase">Trades</span>
                  <span className="text-sm font-semibold text-neutral-300 tabular-nums">
                    {track.trade_count}
                  </span>
                </div>
              </div>

              {/* Execution Bar */}
              <div className="mt-3 pt-3 border-t border-neutral-800">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[9px] text-neutral-600">EXECUTION RATE</span>
                  <span className="text-[9px] text-neutral-500 tabular-nums">
                    {track.total_signals > 0 ? (((track.signals_executed ?? 0) / track.total_signals) * 100).toFixed(0) : 0}%
                  </span>
                </div>
                <div className="w-full bg-neutral-800 h-1">
                  <div
                    className={`h-1 ${
                      (track.total_signals > 0 && (track.signals_executed / track.total_signals) >= 0.5) ? 'bg-blue-500' : 'bg-yellow-600'
                    }`}
                    style={{
                      width: `${track.total_signals > 0 ? (track.signals_executed / track.total_signals) * 100 : 0}%`
                    }}
                  />
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        {/* Legend */}
        <div className="mt-6 pt-4 border-t border-neutral-900">
          <div className="flex flex-wrap gap-4 text-[10px] text-neutral-600">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 bg-blue-700" />
              <span>Real-time Scanner (Track 1)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 bg-purple-700" />
              <span>Whale PNL Tracker (Track 2)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 bg-green-700" />
              <span>Commodity Mean Reversion (Track 3)</span>
            </div>
          </div>
        </div>

        {/* Info Panel */}
        <div className="mt-6 bg-neutral-900/50 border border-neutral-800 p-4">
          <h4 className="text-xs font-semibold text-neutral-400 mb-2">PARALLEL EDGE DISCOVERY</h4>
          <div className="text-[10px] text-neutral-600 space-y-1">
            <p>• <strong className="text-neutral-500">Track 1 - Real-time Scanner:</strong> Price velocity signals from Polymarket WebSocket</p>
            <p>• <strong className="text-neutral-500">Track 2 - Whale PNL Tracker:</strong> Realized PNL ranking from on-chain trades</p>
            <p>• <strong className="text-neutral-500">Track 3 - Commodity MR:</strong> Mean reversion on Kalshi weather markets</p>
            <p className="mt-2 pt-2 border-t border-neutral-800">
              Each track runs in paper trading for 14 days. Tracks with win rate &gt;55% (95% CI) promote to live.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
