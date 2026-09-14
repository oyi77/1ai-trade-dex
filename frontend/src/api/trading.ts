import type {
  DashboardData, Signal, Trade, BotStats, BtcPrice, BtcWindow, TradeAttemptSummary, TradeAttemptsResponse,
} from '../types'
import { api, adminApi } from './core'

export async function fetchDashboard(): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>('/dashboard')
  return data
}

export async function fetchSignals(): Promise<Signal[]> {
  const { data } = await api.get<Signal[]>('/signals')
  return data
}

export async function fetchBtcPrice(): Promise<BtcPrice | null> {
  const { data } = await api.get<BtcPrice | null>('/btc/price')
  return data
}

export async function fetchBtcWindows(): Promise<BtcWindow[]> {
  const { data } = await api.get<BtcWindow[]>('/btc/windows')
  return data
}

export async function fetchTrades(): Promise<Trade[]> {
  const { data } = await api.get<Trade[]>('/trades', { params: { limit: 10000 } })
  return data
}

export async function fetchStats(): Promise<BotStats> {
  const { data } = await api.get<BotStats>('/stats')
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

export interface PolymarketMarket {
  ticker: string
  slug: string
  question: string
  category: string
  yes_price: number
  no_price: number
  volume: number
  liquidity: number
  end_date: string | null
}

export interface PolymarketMarketsResponse {
  markets: PolymarketMarket[]
  total: number
  offset: number
  limit: number
}

export async function fetchPolymarketMarkets(offset = 0, limit = 100, category?: string): Promise<PolymarketMarket[]> {
  const { data } = await api.get<PolymarketMarketsResponse>('/polymarket/markets', {
    params: { offset, limit, category }
  })
  return data.markets
}

export async function runScan(): Promise<{ total_signals: number; actionable_signals: number }> {
  const { data } = await adminApi.post('/run-scan')
  return data
}

export async function simulateTrade(ticker: string): Promise<{ trade_id: number; size: number }> {
  const { data } = await adminApi.post('/simulate-trade', null, {
    params: { signal_ticker: ticker }
  })
  return data
}

export async function startBot(): Promise<{ status: string; is_running: boolean }> {
  const { data } = await adminApi.post('/bot/start')
  return data
}

export async function stopBot(): Promise<{ status: string; is_running: boolean }> {
  const { data } = await adminApi.post('/bot/stop')
  return data
}

export async function settleTradesApi(): Promise<{ settled_count: number }> {
  const { data } = await adminApi.post('/settle-trades')
  return data
}

export async function resetBot(): Promise<{ status: string; trades_deleted: number; new_bankroll: number }> {
  const { data } = await adminApi.post('/bot/reset')
  return data
}

export async function paperTopup(amount: number): Promise<{ status: string; previous_bankroll: number; added: number; new_bankroll: number }> {
  const { data } = await adminApi.post('/bot/paper-topup', { amount, confirm: true })
  return data
}

