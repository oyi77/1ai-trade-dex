
import { api, adminApi } from './core'

export async function approvePendingTrade(id: number): Promise<{ id: number; status: string }> {
  const { data } = await adminApi.post<{ id: number; status: string }>(`/auto-trader/approve/${id}`)
  return data
}

export async function rejectPendingTrade(id: number): Promise<{ id: number; status: string }> {
  const { data } = await adminApi.post<{ id: number; status: string }>(`/auto-trader/reject/${id}`)
  return data
}

export async function batchApprovePendingTrades(ids: number[]): Promise<{ approved_count: number; approved_ids: number[] }> {
  const { data } = await adminApi.post<{ approved_count: number; approved_ids: number[] }>('/auto-trader/batch-approve', { trade_ids: ids })
  return data
}

export async function batchRejectPendingTrades(ids: number[]): Promise<{ rejected_count: number; rejected_ids: number[] }> {
  const { data } = await adminApi.post<{ rejected_count: number; rejected_ids: number[] }>('/auto-trader/batch-reject', { trade_ids: ids })
  return data
}

export async function clearAllPendingTrades(): Promise<{ cleared_count: number; cleared_ids: number[] }> {
  const { data } = await adminApi.post<{ cleared_count: number; cleared_ids: number[] }>('/auto-trader/clear-all')
  return data
}

export interface WhaleTx {
  id: number
  tx_hash: string
  wallet: string
  market_id: string | null
  side: string | null
  size_usd: number
  observed_at: string | null
}

export async function fetchWhaleTransactions(limit = 50): Promise<WhaleTx[]> {
  const { data } = await api.get<WhaleTx[]>('/whales/transactions', { params: { limit } })
  return data
}

export interface ArbOpportunity {
  market_id: string
  kind: string
  net_profit: number
  yes_price?: number
  no_price?: number
}

export async function fetchArbitrageOpportunities(): Promise<ArbOpportunity[]> {
  const { data } = await api.get<{ opportunities: ArbOpportunity[] }>('/arbitrage/opportunities')
  return data.opportunities ?? []
}

// ── Strategy P&L ─────────────────────────────────────────────────────────────────

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

// ── Edge Performance (Parallel Edge Discovery) ───────────────────────────────────

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

// ── Sync Status ──────────────────────────────────────────────────────────────

export async function getSyncStatus(): Promise<import('../types').SyncStatus> {
  const { data } = await adminApi.get<import('../types').SyncStatus>('/admin/sync-status')
  return data
}

export async function triggerManualSync(mode: 'testnet' | 'live'): Promise<{ status: string; message: string }> {
  const { data } = await adminApi.post<{ status: string; message: string }>('/admin/sync-now', null, {
    params: { mode }
  })
  return data}

// ── MiroFish Service Management ────────────────────────────────────────────

