import { useState, useMemo } from 'react'
import { useActivity } from '../hooks/useActivity'
import { useModeFilter } from '../hooks/useModeFilter'

export function ActivityTimeline() {
  const { activities, isConnected, error } = useActivity()
  const { selectedMode } = useModeFilter()
  const [strategyFilter, setStrategyFilter] = useState<string>('all')
  const [decisionFilter, setDecisionFilter] = useState<string>('all')
  const [displayCount, setDisplayCount] = useState(20)

  const uniqueStrategies = useMemo(() => {
    const strategies = new Set(activities.map(a => a.strategy_name))
    return Array.from(strategies).sort()
  }, [activities])

  const filteredActivities = useMemo(() => {
    return activities.filter(activity => {
      if (selectedMode !== 'all' && activity.trading_mode !== selectedMode) return false
      if (strategyFilter !== 'all' && activity.strategy_name !== strategyFilter) return false
      if (decisionFilter !== 'all' && activity.decision_type !== decisionFilter) return false
      return true
    })
  }, [activities, selectedMode, strategyFilter, decisionFilter])

  const displayedActivities = filteredActivities.slice(0, displayCount)
  const hasMore = displayCount < filteredActivities.length

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp)
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).replace(',', '')
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-red-400 text-sm">Error: {error}</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full" data-testid="activity-timeline">
      <div className="shrink-0 border-b border-neutral-800 p-3 flex flex-wrap items-center gap-3 sm:gap-4">
        <div className="flex items-center gap-2">
          <span className={`inline-block w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-400'}`} />
          <span className="text-xs text-neutral-500 uppercase tracking-wider">
            {isConnected ? 'Live' : 'Disconnected'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-neutral-500 uppercase tracking-wider">Strategy:</label>
          <select
            value={strategyFilter}
            onChange={(e) => setStrategyFilter(e.target.value)}
            className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs px-2 py-1 rounded focus:outline-none focus:border-green-500"
          >
            <option value="all">All</option>
            {uniqueStrategies.map(strategy => (
              <option key={strategy} value={strategy}>{strategy}</option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-neutral-500 uppercase tracking-wider">Decision:</label>
          <select
            value={decisionFilter}
            onChange={(e) => setDecisionFilter(e.target.value)}
            className="bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs px-2 py-1 rounded focus:outline-none focus:border-green-500"
          >
            <option value="all">All</option>
            <option value="long">Long</option>
            <option value="short">Short</option>
            <option value="hold">Hold</option>
          </select>
        </div>

        <div className="flex-1" />

        <span className="text-xs text-neutral-500 tabular-nums">
          {filteredActivities.length} activities
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-3" data-testid="activity-list">
        {displayedActivities.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-neutral-500 text-sm">No activities yet</div>
          </div>
        ) : (
          <div className="space-y-2">
            {displayedActivities.map((activity, idx) => (
              <div
                key={activity.id || idx}
                className="bg-neutral-900 border border-neutral-800 rounded p-3 hover:border-neutral-700 transition-colors"
              >
                <div className="flex items-start justify-between gap-2 sm:gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-1">
                      <span className="text-[10px] text-neutral-500 font-mono tabular-nums">
                        {formatTimestamp(activity.timestamp)}
                      </span>
                      <span className="text-xs font-medium text-neutral-300">
                        {activity.strategy_name}
                      </span>
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded uppercase font-bold ${
                          activity.decision_type === 'long'
                            ? 'bg-green-500/10 text-green-400'
                            : activity.decision_type === 'short'
                            ? 'bg-red-500/10 text-red-400'
                            : 'bg-neutral-500/10 text-neutral-400'
                        }`}
                      >
                        {activity.decision_type}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div
                      className={`text-[10px] font-bold px-2 py-1 rounded tabular-nums ${
                        activity.confidence_score >= 0.7
                          ? 'bg-green-500/10 text-green-400'
                          : activity.confidence_score >= 0.5
                          ? 'bg-yellow-500/10 text-yellow-400'
                          : 'bg-red-500/10 text-red-400'
                      }`}
                    >
                      {(activity.confidence_score * 100).toFixed(0)}%
                    </div>
                    <div
                      className={`text-[10px] px-2 py-1 rounded uppercase font-bold ${
                        activity.trading_mode === 'live'
                          ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                          : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                      }`}
                    >
                      {activity.trading_mode}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {hasMore && (
          <div className="flex justify-center mt-4">
            <button
              onClick={() => setDisplayCount(prev => prev + 20)}
              className="px-4 py-2 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider hover:border-green-500/40 hover:text-green-400 transition-colors"
            >
              Load More
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
