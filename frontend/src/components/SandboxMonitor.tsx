import { POLL } from '../polling'
import { useQuery } from '@tanstack/react-query'
import { fetchSandboxScenarios, fetchSandboxResults } from '../api'
import { Loader2, Play, Terminal, RefreshCw, CheckCircle2 } from 'lucide-react'

export interface SandboxScenario {
  name: string
  description: string
}

export interface SandboxValidationResult {
  run_id: string
  timestamp: string
  scenario: string
  status: 'pending' | 'validating' | 'completed' | 'failed'
  result?: {
    success: boolean
    message?: string
    errors?: string[]
    warnings?: string[]
    metrics?: {
      validation_time_ms: number
      lines_of_code: number
      gate_passed: number
      total_gates: number
    }
  }
}

interface Props {
  onValidate?: (code: string, scenario: string) => void
  isValidationRunning?: boolean
}

export function SandboxMonitor({ onValidate, isValidationRunning }: Props) {
  const { data: scenariosData, isLoading: scenariosLoading } = useQuery({
    queryKey: ['sandbox-scenarios'],
    queryFn: fetchSandboxScenarios,
    refetchInterval: POLL.VERY_SLOW,
    staleTime: 60_000,
  })

  const { data: resultsData, isLoading: resultsLoading } = useQuery({
    queryKey: ['sandbox-results'],
    queryFn: fetchSandboxResults,
    refetchInterval: POLL.SLOW,
    staleTime: 30_000,
  })

  const scenarios = (scenariosData?.scenarios || []) as SandboxScenario[]
  const results = (resultsData?.results || []) as SandboxValidationResult[]

  if (scenariosLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-4 h-4 text-neutral-500 animate-spin" />
      </div>
    )
  }

  const getCurrentStatus = (status: SandboxValidationResult['status']) => {
    switch (status) {
      case 'pending':
        return { icon: <Loader2 className="w-2.5 h-2.5 text-amber-500 animate-pulse" />, label: 'PENDING' }
      case 'validating':
        return { icon: <Loader2 className="w-2.5 h-2.5 text-blue-500 animate-spin" />, label: 'VALIDATING' }
      case 'completed':
        return { icon: <CheckCircle2 className="w-2.5 h-2.5 text-green-500" />, label: 'PASSED' }
      case 'failed':
        return { icon: <Terminal className="w-2.5 h-2.5 text-red-500" />, label: 'FAILED' }
      default:
        return { icon: <Loader2 className="w-2.5 h-2.5 text-neutral-500" />, label: 'UNKNOWN' }
    }
  }

  return (
    <div className="space-y-3 overflow-y-auto max-h-full">
      {/* Quick validation widget */}
      <div className="bg-gradient-to-br from-neutral-900 to-neutral-950 border border-neutral-800 rounded p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Play className="w-3.5 h-3.5 text-emerald-500" />
            <span className="text-[10px] font-semibold text-neutral-200">VALIDATE STRATEGY</span>
          </div>
          {isValidationRunning && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <label className="text-[8px] text-neutral-500 uppercase">Scenario</label>
            <select
              className="w-full bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-[9px] text-neutral-300 focus:outline-none focus:border-neutral-600"
              defaultValue="default"
            >
              {scenarios.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => onValidate?.('', 'default')}
            disabled={isValidationRunning}
            className="bg-emerald-600/20 hover:bg-emerald-600/30 disabled:bg-neutral-800 disabled:text-neutral-600 text-emerald-400 text-[9px] px-3 py-1.5 rounded transition-colors h-full flex items-center justify-center gap-1.5"
          >
            {isValidationRunning ? 'RUNNING...' : <Play className="w-2.5 h-2.5" />}
            VALIDATE
          </button>
        </div>
      </div>

      {/* Recent validation results */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[9px] font-medium text-neutral-500 uppercase tracking-wider">
            Recent Results
          </span>
          <RefreshCw
            className="w-3 h-3 text-neutral-600 hover:text-neutral-400 cursor-pointer"
            onClick={() => resultsData && fetchSandboxResults()}
          />
        </div>

        {resultsLoading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-16 bg-neutral-800/50 rounded animate-pulse" />
            ))}
          </div>
        ) : results.length === 0 ? (
          <div className="text-center py-6">
            <Terminal className="w-6 h-6 text-neutral-700 mx-auto mb-2" />
            <p className="text-[10px] text-neutral-600">No validation runs yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {results.slice(0, 10).map((result) => {
              const statusInfo = getCurrentStatus(result.status)
              return (
                <div
                  key={result.run_id}
                  className="bg-neutral-900/50 border border-neutral-800 rounded p-2.5 hover:border-neutral-700 transition-colors"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {statusInfo.icon}
                      <span className="text-[9px] font-medium text-neutral-300 font-mono">
                        {result.run_id.slice(0, 8)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[8px] text-neutral-500 font-mono">
                        {new Date(result.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 text-[9px]">
                    <div className="flex-1">
                      <div className="text-neutral-500">Scenario</div>
                      <div className="text-neutral-300 font-medium">{result.scenario}</div>
                    </div>
                    <div className="w-px h-6 bg-neutral-800" />
                    <div className="flex-1">
                      <div className="text-neutral-500">Result</div>
                      <div className={`font-medium ${result.status === 'failed' ? 'text-red-400' : 'text-green-400'}`}>
                        {result.status === 'completed' ? 'PASSED' : result.status.toUpperCase()}
                      </div>
                    </div>
                  </div>

                  {result.result && result.result.errors && result.result.errors.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {result.result.errors.slice(0, 2).map((err, i) => (
                        <div key={i} className="text-[8px] text-red-400/80 font-mono pl-2 border-l-2 border-red-500/30">
                          {err}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default SandboxMonitor
