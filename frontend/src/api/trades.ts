import type { Trade, TradeAttemptSummary, TradeAttemptsResponse, DashboardData, BotStats } from '../types'
import { api, adminApi } from './client'

export async function fetchDashboard(): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>('/dashboard')
  return data
}

export async function fetchStats(): Promise<BotStats> {
  const { data } = await api.get<BotStats>('/stats')
  return data
}

export async function fetchTrades(): Promise<Trade[]> {
  const { data } = await api.get<Trade[]>('/trades', { params: { limit: 10000 } })
  return data
}

export async function fetchTradeAttempts(params?: Record<string, string | number>): Promise<TradeAttemptsResponse> {
  const { data } = await api.get<TradeAttemptsResponse>('/trade-attempts', { params })
  return data
}

export async function fetchTradeAttemptSummary(params?: Record<string, string | number>): Promise<TradeAttemptSummary> {
  const { data } = await api.get<TradeAttemptSummary>('/trade-attempts/summary', { params })
  return data
}

/** Alias for fetchTradeAttemptSummary */
export const fetchTradeSummary = fetchTradeAttemptSummary

export async function executeTrade(ticker: string): Promise<{ trade_id: number; size: number }> {
  const { data } = await adminApi.post('/simulate-trade', null, {
    params: { signal_ticker: ticker }
  })
  return data
}

export async function settleTradesApi(): Promise<{ settled_count: number }> {
  const { data } = await adminApi.post('/settle-trades')
  return data
}

export interface SettlementEvent {
  id: number
  trade_id: number
  market_ticker: string
  resolved_outcome: string | null
  pnl: number | null
  settled_at: string | null
  source: string
}

export async function fetchSettlements(limit = 100, offset = 0): Promise<SettlementEvent[]> {
  const { data } = await api.get<SettlementEvent[]>('/settlements', { params: { limit, offset } })
  return data
}

export interface SignalHistoryRow {
  id: number
  market_ticker: string
  platform: string
  market_type: string
  timestamp: string | null
  direction: string
  model_probability: number
  market_probability: number
  edge: number
  confidence: number | null
  suggested_size: number | null
  reasoning: string | null
  executed: boolean
  actual_outcome: string | null
  outcome_correct: boolean | null
  settlement_value: number | null
  settled_at: string | null
  trading_mode: string
  execution_mode: string
}

export async function fetchSignalHistory(params?: { limit?: number; offset?: number; market_type?: string; direction?: string }): Promise<{ items: SignalHistoryRow[]; total: number }> {
  const { data } = await api.get('/signals/history', { params })
  return data
}
