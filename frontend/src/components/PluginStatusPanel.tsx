import { POLL } from '../polling'
import { useQuery } from '@tanstack/react-query'
import { fetchPluginStatus } from '../api'
import { RefreshCw } from 'lucide-react'

export interface PluginStatus {
  name: string
  enabled: boolean
  version: string
  last_updated: string
  status: 'healthy' | 'warning' | 'error'
  error_message?: string
  metrics?: {
    requests_total: number
    requests_success: number
    requests_failed: number
    avg_latency_ms: number
  }
}

interface Props {
  onEnable?: (name: string) => void
  onDisable?: (name: string) => void
}

export function PluginStatusPanel({ onEnable, onDisable }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['plugin-status'],
    queryFn: fetchPluginStatus,
    refetchInterval: POLL.SLOW,
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <RefreshCw className="w-4 h-4 text-neutral-500 animate-spin" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="text-[10px] text-red-500/60 p-2 text-center">
        Failed to load plugin status
      </div>
    )
  }

  const plugins = (data?.plugins || []) as PluginStatus[]

  if (plugins.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-center px-4">
        <div className="text-neutral-600 text-[10px]">
          No plugins detected. System running in core mode.
        </div>
      </div>
    )
  }

  const getstatusColor = (status: PluginStatus['status']) => {
    switch (status) {
      case 'healthy':
        return 'bg-green-500/20 text-green-400 border-green-500/30'
      case 'warning':
        return 'bg-amber-500/20 text-amber-400 border-amber-500/30'
      case 'error':
        return 'bg-red-500/20 text-red-400 border-red-500/30'
      default:
        return 'bg-neutral-800 text-neutral-400 border-neutral-700'
    }
  }

  return (
    <div className="space-y-2 overflow-y-auto max-h-full">
      {plugins.map((plugin) => (
        <div
          key={plugin.name}
          className="bg-neutral-900/50 border border-neutral-800 rounded p-3 space-y-2 hover:border-neutral-700 transition-colors"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${plugin.enabled ? 'bg-green-500' : 'bg-red-500'}`}
              />
              <span className="text-[10px] font-medium text-neutral-200">{plugin.name}</span>
              <span className="text-[8px] text-neutral-500 px-1 py-0.5 bg-neutral-800 rounded">
                v{plugin.version}
              </span>
            </div>
            <span className={`text-[8px] px-1.5 py-0.5 rounded border ${getstatusColor(plugin.status)}`}>
              {plugin.status.toUpperCase()}
            </span>
          </div>

          {plugin.metrics && (
            <div className="grid grid-cols-3 gap-1 mt-2">
              <div className="text-[9px] text-neutral-500">
                <div className="text-neutral-400">Requests</div>
                <div className="tabular-nums text-neutral-300">
                  {plugin.metrics.requests_total.toLocaleString()}
                </div>
              </div>
              <div className="text-[9px] text-neutral-500">
                <div className="text-neutral-400">Success</div>
                <div className="tabular-nums text-neutral-300">
                  {plugin.metrics.requests_success.toLocaleString()}
                </div>
              </div>
              <div className="text-[9px] text-neutral-500">
                <div className="text-neutral-400">Latency</div>
                <div className="tabular-nums text-neutral-300">
                  {plugin.metrics.avg_latency_ms.toFixed(0)}ms
                </div>
              </div>
            </div>
          )}

          {plugin.error_message && (
            <div className="text-[9px] text-red-400/80 mt-1 whitespace-pre-wrap">
              {plugin.error_message}
            </div>
          )}

          <div className="flex gap-2 mt-2 pt-2 border-t border-neutral-800">
            <button
              onClick={() => onEnable?.(plugin.name)}
              disabled={plugin.enabled}
              className={`flex-1 text-[9px] px-2 py-1 rounded transition-colors ${
                plugin.enabled
                  ? 'bg-neutral-800 text-neutral-600 cursor-not-allowed'
                  : 'bg-green-500/10 text-green-400 hover:bg-green-500/20'
              }`}
            >
              ENABLE
            </button>
            <button
              onClick={() => onDisable?.(plugin.name)}
              disabled={!plugin.enabled}
              className={`flex-1 text-[9px] px-2 py-1 rounded transition-colors ${
                !plugin.enabled
                  ? 'bg-neutral-800 text-neutral-600 cursor-not-allowed'
                  : 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
              }`}
            >
              DISABLE
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

export default PluginStatusPanel
