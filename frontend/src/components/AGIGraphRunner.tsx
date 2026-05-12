import { POLL } from '../polling'
import { useQuery } from '@tanstack/react-query'
import { fetchAGIGraphs, fetchAGIRunResult } from '../api'
import { Play, RefreshCw, Terminal, CheckCircle2, AlertTriangle } from 'lucide-react'

export interface AGIGraphNode {
  id: string
  label: string
  type: string
  status: string
  data?: any
}

export interface AGIGraphEdge {
  source: string
  target: string
  label?: string
}

export interface AGIGraph {
  name: string
  nodes: AGIGraphNode[]
  edges: AGIGraphEdge[]
}

export interface AGIRunResult {
  run_id: string
  graph_name: string
  timestamp: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: {
    success: boolean
    data?: any
    errors?: string[]
  }
}

interface Props {
  onRunGraph?: (name: string, initialData?: any) => void
  isRunning?: boolean
}

export function AGIGraphRunner({ onRunGraph, isRunning }: Props) {
  const { data: graphsData, isLoading: graphsLoading } = useQuery({
    queryKey: ['agi-graphs'],
    queryFn: fetchAGIGraphs,
    refetchInterval: POLL.VERY_SLOW,
    staleTime: 60_000,
  })

  const { data: resultsData, isLoading: resultsLoading } = useQuery({
    queryKey: ['agi-run-results'],
    queryFn: fetchAGIRunResult,
    refetchInterval: POLL.SLOW,
    staleTime: 30_000,
  })

  const graphs = (graphsData?.graphs || []) as AGIGraph[]
  const results = (resultsData?.results || []) as AGIRunResult[]

  if (graphsLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <RefreshCw className="w-4 h-4 text-neutral-500 animate-spin" />
      </div>
    )
  }

  const getStatusBadge = (status: AGIRunResult['status']) => {
    switch (status) {
      case 'pending':
        return <div className="w-2 h-2 rounded-full bg-amber-500/20" />
      case 'running':
        return <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
      case 'completed':
        return <CheckCircle2 className="w-2.5 h-2.5 text-green-500" />
      case 'failed':
        return <AlertTriangle className="w-2.5 h-2.5 text-red-500" />
      default:
        return <div className="w-2 h-2 rounded-full bg-neutral-600" />
    }
  }

  return (
    <div className="space-y-3 overflow-y-auto max-h-full">
      {/* Graph selection */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[9px] font-medium text-neutral-500 uppercase tracking-wider">
            Available Graphs
          </span>
          <span className="text-[8px] text-neutral-600">{graphs.length} graphs</span>
        </div>

        {graphsLoading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 bg-neutral-800/50 rounded animate-pulse" />
            ))}
          </div>
        ) : graphs.length === 0 ? (
          <div className="text-center py-6">
            <Terminal className="w-6 h-6 text-neutral-700 mx-auto mb-2" />
            <p className="text-[10px] text-neutral-600">No graphs configured</p>
          </div>
        ) : (
          <div className="space-y-2">
            {graphs.map((graph) => (
              <div
                key={graph.name}
                className="bg-neutral-900/50 border border-neutral-800 rounded p-2.5 hover:border-neutral-700 transition-colors"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Play className="w-3 h-3 text-emerald-500" />
                    <span className="text-[10px] font-medium text-neutral-200">{graph.name}</span>
                    <span className="text-[8px] text-neutral-500">
                      {graph.nodes.length} nodes
                    </span>
                  </div>
                  <button
                    onClick={() => onRunGraph?.(graph.name, {})}
                    disabled={isRunning}
                    className="bg-emerald-600/20 hover:bg-emerald-600/30 disabled:bg-neutral-800 disabled:text-neutral-600 text-emerald-400 text-[9px] px-2 py-1 rounded transition-colors"
                  >
                    {isRunning ? 'RUNNING...' : 'RUN'}
                  </button>
                </div>

                <div className="space-y-1">
                  <div className="flex items-center gap-1.5">
                    <div className="h-px flex-1 bg-neutral-800" />
                    <div className="text-[7px] text-neutral-500 uppercase">Nodes</div>
                    <div className="h-px flex-1 bg-neutral-800" />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {graph.nodes.slice(0, 6).map((node, i) => (
                      <span
                        key={i}
                        className="text-[7px] px-1.5 py-0.5 bg-neutral-800 rounded text-neutral-400"
                      >
                        {node.label}
                      </span>
                    ))}
                    {graph.nodes.length > 6 && (
                      <span className="text-[7px] px-1.5 py-0.5 bg-neutral-800 rounded text-neutral-500">
                        +{graph.nodes.length - 6} more
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent runs */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[9px] font-medium text-neutral-500 uppercase tracking-wider">
            Recent Runs
          </span>
          <RefreshCw
            className="w-3 h-3 text-neutral-600 hover:text-neutral-400 cursor-pointer"
            onClick={() => resultsData && fetchAGIRunResult()}
          />
        </div>

        {resultsLoading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 bg-neutral-800/50 rounded animate-pulse" />
            ))}
          </div>
        ) : results.length === 0 ? (
          <div className="text-center py-6">
            <Terminal className="w-6 h-6 text-neutral-700 mx-auto mb-2" />
            <p className="text-[10px] text-neutral-600">No runs yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {results.slice(0, 8).map((run) => (
              <div
                key={run.run_id}
                className="bg-neutral-900/50 border border-neutral-800 rounded p-2 hover:border-neutral-700 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {getStatusBadge(run.status)}
                    <span className="text-[9px] font-mono text-neutral-300">
                      {run.run_id.slice(0, 8)}
                    </span>
                    <span className="text-[8px] text-neutral-500">{run.graph_name}</span>
                  </div>
                  <span className="text-[8px] text-neutral-600">
                    {new Date(run.timestamp).toLocaleTimeString()}
                  </span>
                </div>

                {run.result?.errors && run.result.errors.length > 0 && (
                  <div className="mt-1.5 space-y-0.5">
                    {run.result.errors.slice(0, 3).map((err, i) => (
                      <div
                        key={i}
                        className="text-[8px] text-red-400/70 font-mono pl-2 border-l border-red-500/20"
                      >
                        {err}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default AGIGraphRunner
