import { api } from './client'

export interface WhaleTx {
  id: number
  tx_hash: string
  wallet: string
  market_id: string | null
  side: string | null
  size_usd: number
  observed_at: string | null
}

export async function fetchWhaleActivity(limit = 50): Promise<WhaleTx[]> {
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

export interface ScoredTrader {
  wallet: string
  pseudonym: string
  profit_30d: number
  win_rate: number
  total_trades: number
  unique_markets: number
  estimated_bankroll: number
  score: number
  market_diversity: number
}

export async function fetchCopyLeaderboard(): Promise<ScoredTrader[]> {
  const { data } = await api.get<ScoredTrader[]>('/copy/leaderboard', { params: { limit: 100 } })
  return data
}

export async function fetchWhalePnL(wallet?: string): Promise<{
  total_pnl: number
  win_rate: number
  total_trades: number
  trades: Array<{ market: string; pnl: number; outcome: string }>
}> {
  const params = wallet ? { wallet } : {}
  const { data } = await api.get('/whales/pnl', { params })
  return data
}
