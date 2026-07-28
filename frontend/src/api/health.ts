import { api } from './client'

export interface StrategyHealth {
  name: string
  last_heartbeat: string | null
  lag_seconds: number | null
  healthy: boolean
}

export async function fetchHealth(): Promise<{ strategies: StrategyHealth[]; bot_running: boolean }> {
  const { data } = await api.get('/health/ready')
  return data
}

export async function fetchDetailedHealth(): Promise<{
  status: string
  uptime: number
  version: string
  dependencies: Record<string, 'healthy' | 'degraded' | 'down'>
}> {
  const { data } = await api.get('/health/detailed')
  return data
}

export async function fetchAGIHealth(): Promise<{
  status: string
  last_cycle: string | null
  cycle_count: number
  errors_last_24h: number
}> {
  const { data } = await api.get('/health/agi')
  return data
}
