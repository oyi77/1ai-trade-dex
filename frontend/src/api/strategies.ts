import { api, adminApi } from './client'

export interface StrategyConfig {
  name: string
  description: string
  category: string
  enabled: boolean
  interval_seconds: number
  params: Record<string, unknown>
  default_params: Record<string, unknown>
  updated_at: string | null
  required_credentials?: string[]
}

export async function fetchStrategies(): Promise<StrategyConfig[]> {
  const { data } = await api.get('/strategies')
  return data
}

export interface StrategyHealth {
  name: string
  last_heartbeat: string | null
  lag_seconds: number | null
  healthy: boolean
}

export async function fetchStrategyHealth(): Promise<StrategyHealth[]> {
  const { data } = await api.get('/health/ready')
  return data.strategies
}

export async function fetchStrategyDetail(name: string): Promise<StrategyConfig> {
  const { data } = await api.get(`/strategies/${name}`)
  return data
}

export async function updateStrategy(name: string, body: { enabled?: boolean; interval_seconds?: number; params?: Record<string, unknown>; trading_mode?: string | null }): Promise<StrategyConfig> {
  const { data } = await adminApi.put(`/strategies/${name}`, body)
  return data
}

export async function runStrategyNow(name: string): Promise<{ status: string }> {
  const { data } = await adminApi.post(`/strategies/${name}/run-now`)
  return data
}

export async function compareStrategies(names: string[]): Promise<Record<string, unknown>> {
  const { data } = await api.post('/strategies/compare', { names })
  return data
}

export interface StrategyPnL {
  strategy: string
  total_trades: number
  wins: number
  losses: number
  pending: number
  win_rate: number
  total_pnl: number
  avg_edge: number
  avg_size: number
}

export async function fetchStrategyStats(): Promise<{ strategies: StrategyPnL[] }> {
  const { data } = await api.get('/stats/strategies')
  return data
}

export interface EdgePerformanceTrack {
  track_name: string
  total_signals: number
  signals_executed: number
  winning_trades: number
  win_rate: number
  total_pnl: number
  trade_count: number
  status: string
}

export interface EdgePerformanceResponse {
  tracks: EdgePerformanceTrack[]
  days: number
  since_date: string
}

export async function fetchEdgePerformance(days = 7): Promise<EdgePerformanceResponse> {
  const { data } = await api.get<EdgePerformanceResponse>('/edge-performance', { params: { days } })
  return data
}
