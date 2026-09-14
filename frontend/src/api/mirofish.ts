
import { api, adminApi } from './core'

export interface MiroFishServiceStatus {
  state: 'running' | 'paused' | 'stopped'
  started_at: string | null
  uptime_seconds: number | null
  last_signal_fetch: string | null
  total_signals_fetched: number
  error_message: string | null
  monitor: {
    health_status: string
    latency_ms: number
    error_rate: number
    circuit_breaker_state: string
    total_requests: number
    failed_requests: number
    consecutive_failures: number
    last_success_time: string | null
    last_failure_time: string | null
    circuit_breaker_config?: Record<string, unknown>
  }
}

export interface MiroFishServiceAction {
  success: boolean
  message: string
  state: string
  data?: MiroFishServiceStatus
}

export async function fetchMiroFishStatus(): Promise<MiroFishServiceStatus> {
  const { data } = await api.get<MiroFishServiceStatus>('/settings/mirofish/status')
  return data
}

export async function mirofishStart(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/start')
  return data
}

export async function mirofishStop(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/stop')
  return data
}

export async function mirofishPause(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/pause')
  return data
}

export async function mirofishRestart(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/restart')
  return data
}

// ── MiroFish Process Management ────────────────────────────────────────────

export interface MiroFishProcessStatus {
  backend_running: boolean
  backend_pid: number | null
  frontend_running: boolean
  frontend_pid: number | null
}

export interface MiroFishProcessAction {
  success: boolean
  results: { backend: string; frontend: string }
}

export async function fetchMiroFishProcesses(): Promise<MiroFishProcessStatus> {
  const { data } = await adminApi.get<MiroFishProcessStatus>('/settings/mirofish/processes')
  return data
}

export async function startMiroFishProcesses(): Promise<MiroFishProcessAction> {
  const { data } = await adminApi.post<MiroFishProcessAction>('/settings/mirofish/processes/start')
  return data
}

export async function stopMiroFishProcesses(): Promise<MiroFishProcessAction> {
  const { data } = await adminApi.post<MiroFishProcessAction>('/settings/mirofish/processes/stop')
  return data
}

export async function restartMiroFishProcesses(): Promise<MiroFishProcessAction> {
  const { data } = await adminApi.post<MiroFishProcessAction>('/settings/mirofish/processes/restart')
  return data
}

