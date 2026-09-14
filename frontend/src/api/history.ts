import type {
  WeatherForecast, WeatherSignal, Setting,
} from '../types'
import { api, adminApi } from './core'

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

export async function fetchWeatherForecasts(): Promise<WeatherForecast[]> {
  const { data } = await api.get<WeatherForecast[]>('/weather/forecasts')
  return data
}

export async function fetchWeatherSignals(): Promise<WeatherSignal[]> {
  const { data } = await api.get<WeatherSignal[]>('/weather/signals')
  return data
}

export async function changeAdminPassword(newPassword: string): Promise<{ status: string; message: string }> {
  const { data } = await adminApi.post('/admin/change-password', { new_password: newPassword })
  return data
}

// Admin API (uses adminApi which injects Authorization header)
export async function fetchAdminSettings(): Promise<Setting[]> {
  const { data } = await adminApi.get<Setting[]>('/settings/list')
  return data
}

export async function updateAdminSettings(updates: Array<{ key: string; value: string }>): Promise<{ status: string; message: string; updated: number }> {
  const { data } = await adminApi.put('/settings/list', { updates })
  return data
}

export async function toggleTradingMode(mode: 'paper' | 'testnet' | 'live', active: boolean): Promise<{ status: string; mode: string; active: boolean; active_modes: string[] }> {
  const { data } = await adminApi.post('/admin/mode', { mode, active })
  return data
}

