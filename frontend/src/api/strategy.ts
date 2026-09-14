import { api, adminApi, API_BASE } from './core'

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

export async function updateStrategy(name: string, body: { enabled?: boolean; interval_seconds?: number; params?: Record<string, unknown>; trading_mode?: string | null }): Promise<StrategyConfig> {
  const { data } = await adminApi.put(`/strategies/${name}`, body)
  return data
}

export async function runStrategyNow(name: string): Promise<{ status: string }> {
  const { data } = await adminApi.post(`/strategies/${name}/run-now`)
  return data
}

// ── Market Watch ──────────────────────────────────────────────────────────────

export interface MarketWatchRow {
  id: number
  ticker: string
  category: string
  source: string
  enabled: boolean
  created_at: string | null
}

export async function fetchMarketWatches(params?: Record<string, string | number | boolean>): Promise<{ items: MarketWatchRow[]; total: number }> {
  const { data } = await api.get('/markets/watch', { params })
  return data
}

export async function createMarketWatch(body: { ticker: string; category?: string; source?: string; enabled?: boolean }): Promise<MarketWatchRow> {
  const { data } = await adminApi.post('/markets/watch', body)
  return data
}

export async function deleteMarketWatch(id: number): Promise<void> {
  await adminApi.delete(`/markets/watch/${id}`)
}

// ── Decision Log ──────────────────────────────────────────────────────────────

export interface DecisionLogRow {
  id: number
  strategy: string
  market_ticker: string
  decision: string
  confidence: number | null
  reason: string | null
  outcome: string | null
  created_at: string | null
  signal_data?: Record<string, unknown> | null
}

export interface DecisionLogDetail extends DecisionLogRow {
  signal_data: Record<string, unknown> | null
}

export async function fetchDecisions(params?: Record<string, string | number>): Promise<{ items: DecisionLogRow[]; total: number }> {
  const { data } = await api.get('/decisions', { params })
  return data
}

export async function fetchDecision(id: number): Promise<DecisionLogDetail> {
  const { data } = await api.get(`/decisions/${id}`)
  return data
}

export function decisionsExportUrl(params?: Record<string, string>): string {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return `${API_BASE}/api/v1/decisions/export${qs}`
}

// ── Health ────────────────────────────────────────────────────────────────────

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

// ── Signal Config (public, no auth) ────────────────────────────────────────────

