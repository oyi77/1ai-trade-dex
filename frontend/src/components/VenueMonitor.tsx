import { POLL } from '../polling'
import { useQuery } from '@tanstack/react-query'
import { fetchVenueData } from '../api'
import { Activity, TrendingUp, TrendingDown, AlertTriangle, CheckCircle2 } from 'lucide-react'

export interface VenueMetric {
  name: string
  value: number | string
  trend?: 'up' | 'down' | 'neutral'
  change?: number
}

export interface VenueStatus {
  venue: string
  connected: boolean
  last_seen: string
  metrics: VenueMetric[]
  status: 'healthy' | 'warning' | 'error'
  latency_ms: number
  issues?: string[]
}

interface Props {
  venueFilter?: string
}

export function VenueMonitor({ venueFilter }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['venue-monitor'],
    queryFn: fetchVenueData,
    refetchInterval: POLL.FAST,
    staleTime: 10_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-2">
          <Activity className="w-4 h-4 text-neutral-500 animate-spin" />
          <span className="text-[10px] text-neutral-500">Updating venue status...</span>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="text-[10px] text-red-500/60 p-2 text-center">
        Venue monitoring unavailable
      </div>
    )
  }

  const venues = (data?.venues || []) as VenueStatus[]
  const filteredVenues = venueFilter
    ? venues.filter((v) => v.venue.toLowerCase() === venueFilter.toLowerCase())
    : venues

  if (filteredVenues.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-center px-4">
        <div className="text-neutral-600 text-[10px]">
          No venue data available
        </div>
      </div>
    )
  }

  const StatusBadge = ({ connected }: { connected: boolean }) =>
    connected ? (
      <CheckCircle2 className="w-3 h-3 text-green-500" />
    ) : (
      <AlertTriangle className="w-3 h-3 text-red-500" />
    )

  const TrendIcon = ({ trend }: { trend?: 'up' | 'down' | 'neutral' }) => {
    switch (trend) {
      case 'up':
        return <TrendingUp className="w-2.5 h-2.5 text-green-500" />
      case 'down':
        return <TrendingDown className="w-2.5 h-2.5 text-red-500" />
      default:
        return <div className="w-2.5 h-2.5" />
    }
  }

  return (
    <div className="space-y-2 overflow-y-auto max-h-full">
      {filteredVenues.map((venue) => (
        <div
          key={venue.venue}
          className={`bg-neutral-900/50 border rounded p-3 space-y-2 transition-colors ${
            venue.status === 'error'
              ? 'border-red-500/30'
              : venue.status === 'warning'
              ? 'border-amber-500/30'
              : 'border-neutral-800 hover:border-neutral-700'
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <StatusBadge connected={venue.connected} />
              <span className="text-[10px] font-medium text-neutral-200 uppercase">
                {venue.venue}
              </span>
            </div>
            <span className="text-[8px] text-neutral-500">
              {venue.connected ? `${venue.latency_ms}ms` : 'disconnected'}
            </span>
          </div>

          {venue.issues && venue.issues.length > 0 && (
            <div className="space-y-1 mt-2">
              {venue.issues.slice(0, 2).map((issue, i) => (
                <div key={i} className="text-[9px] text-amber-400/80 flex items-center gap-1.5">
                  <AlertTriangle className="w-2.5 h-2.5 shrink-0" />
                  <span>{issue}</span>
                </div>
              ))}
              {venue.issues.length > 2 && (
                <div className="text-[9px] text-neutral-500 pl-3.5">
                  +{venue.issues.length - 2} more
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-neutral-800">
            {venue.metrics.slice(0, 4).map((metric, i) => (
              <div key={i} className="text-[9px]">
                <div className="text-neutral-500 truncate">{metric.name}</div>
                <div className="flex items-center gap-1.5 text-neutral-200">
                  <span className="tabular-nums">{metric.value}</span>
                  {metric.trend && <TrendIcon trend={metric.trend} />}
                  {metric.change && metric.change !== 0 && (
                    <span
                      className={`text-[8px] ${
                        metric.change > 0 ? 'text-green-500' : 'text-red-500'
                      }`}
                    >
                      {metric.change > 0 ? '+' : ''}
                      {metric.change}%
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export default VenueMonitor
