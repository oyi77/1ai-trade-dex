import { api, adminApi } from './client'

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

export async function fetchMarkets(offset = 0, limit = 100, category?: string): Promise<PolymarketMarket[]> {
  const { data } = await api.get<PolymarketMarketsResponse>('/polymarket/markets', {
    params: { offset, limit, category }
  })
  return data.markets
}

export async function fetchMarketDetail(ticker: string): Promise<PolymarketMarket & { description?: string; volume_24h?: number }> {
  const { data } = await api.get(`/markets/${ticker}`)
  return data
}

export interface Signal {
  market_ticker: string
  market_title: string
  platform: string
  market_type: string
  timestamp: string
  direction: string
  edge: number
  confidence: number | null
  suggested_size: number | null
  outcome: string | null
  signal_type?: string
  reason?: string
}

export async function fetchSignals(): Promise<Signal[]> {
  const { data } = await api.get<Signal[]>('/signals')
  return data
}

export interface BtcPrice {
  price: number
  change_24h: number
  change_7d: number
  market_cap: number
  volume_24h: number
  last_updated: string
}

export async function fetchBtcPrice(): Promise<BtcPrice | null> {
  const { data } = await api.get<BtcPrice | null>('/btc/price')
  return data
}

export interface BtcWindow {
  slug: string
  market_id: string
  up_price: number
  down_price: number
  window_start: string
  window_end: string
  volume: number
  is_active: boolean
  is_upcoming: boolean
  time_until_end: number
  spread: number
}

export async function fetchBtcWindows(): Promise<BtcWindow[]> {
  const { data } = await api.get<BtcWindow[]>('/btc/windows')
  return data
}

export interface WeatherForecast {
  market_ticker: string
  forecast: string
  confidence: number
  issued_at: string
}

export interface WeatherSignal {
  market_ticker: string
  direction: string
  edge: number
  forecast: string
}

export async function fetchWeatherForecasts(): Promise<WeatherForecast[]> {
  const { data } = await api.get<WeatherForecast[]>('/weather/forecasts')
  return data
}

export async function fetchWeatherSignals(): Promise<WeatherSignal[]> {
  const { data } = await api.get<WeatherSignal[]>('/weather/signals')
  return data
}

export interface SignalConfig {
  approval_mode: 'manual' | 'auto_approve' | 'auto_deny'
  min_confidence: number
  notification_duration_ms: number
}

export async function fetchSignalConfig(): Promise<SignalConfig> {
  const { data } = await api.get('/signal-config')
  return data
}

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
