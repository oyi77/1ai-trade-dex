import type { Setting } from '../types'
import { api, adminApi } from './client'

export async function fetchSettings(): Promise<Setting[]> {
  const { data } = await adminApi.get<Setting[]>('/settings/list')
  return data
}

export async function updateSettings(updates: Array<{ key: string; value: string }>): Promise<{ status: string; message: string; updated: number }> {
  const { data } = await adminApi.put('/settings/list', { updates })
  return data
}

export async function fetchSystemStatus(): Promise<{
  trading_mode: string
  active_modes: string[]
  bot_running: boolean
  uptime_seconds: number
  pending_trades: number
  telegram_configured: boolean
  kalshi_enabled: boolean
  weather_enabled: boolean
  db_trade_count: number
  db_signal_count: number
  creds_paper: boolean
  creds_testnet: boolean
  creds_live: boolean
  missing_for_testnet: string[]
  missing_for_live: string[]
  builder_configured: boolean
  signature_type: number
  signature_type_label: string
}> {
  const { data } = await adminApi.get('/admin/system')
  return data
}

export async function fetchAuditLogs(params?: Record<string, string | number>): Promise<{ items: Record<string, unknown>[]; total: number }> {
  const { data } = await adminApi.get('/admin/audit-logs', { params })
  return data
}

export async function fetchProviderCredentials(): Promise<{
  creds_paper: boolean
  creds_testnet: boolean
  creds_live: boolean
  missing_for_testnet: string[]
  missing_for_live: string[]
  builder_configured: boolean
  signature_type: number
}> {
  const { data } = await adminApi.get('/admin/system')
  return data
}

export async function updateProviderCredentials(creds: {
  private_key?: string
  api_key?: string
  api_secret?: string
  api_passphrase?: string
  signature_type?: number
  builder_api_key?: string
  builder_secret?: string
  builder_passphrase?: string
  relayer_api_key?: string
  relayer_api_key_address?: string
}): Promise<{
  status: string
  updated: string[]
  creds_paper: boolean
  creds_testnet: boolean
  creds_live: boolean
  missing_for_testnet: string[]
  missing_for_live: string[]
  builder_configured: boolean
  signature_type: number
}> {
  const { data } = await adminApi.post('/admin/credentials', creds)
  return data
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

export async function changeAdminPassword(newPassword: string): Promise<{ status: string; message: string }> {
  const { data } = await adminApi.post('/admin/change-password', { new_password: newPassword })
  return data
}

export async function toggleTradingMode(mode: 'paper' | 'testnet' | 'live', active: boolean): Promise<{ status: string; mode: string; active: boolean; active_modes: string[] }> {
  const { data } = await adminApi.post('/admin/mode', { mode, active })
  return data
}

export async function updateBitgetWalletCredentials(creds: {
  api_key?: string
  api_secret?: string
  api_passphrase?: string
}): Promise<{ status: string; applied: Record<string, string>; skipped: Record<string, string> }> {
  const updates: Record<string, string> = {}
  if (creds.api_key) updates.BITGET_WALLET_API_KEY = creds.api_key
  if (creds.api_secret) updates.BITGET_WALLET_API_SECRET = creds.api_secret
  if (creds.api_passphrase) updates.BITGET_WALLET_API_PASSPHRASE = creds.api_passphrase
  const { data } = await adminApi.post('/admin/settings', { updates })
  return data
}

export async function getSyncStatus(): Promise<import('../types').SyncStatus> {
  const { data } = await adminApi.get<import('../types').SyncStatus>('/admin/sync-status')
  return data
}

export async function triggerManualSync(mode: 'testnet' | 'live'): Promise<{ status: string; message: string }> {
  const { data } = await adminApi.post<{ status: string; message: string }>('/admin/sync-now', null, {
    params: { mode }
  })
  return data
}

export interface PluginStatus {
  name: string
  enabled: boolean
  version: string
  last_updated: string
  status: 'healthy' | 'warning' | 'error'
  error_message?: string
  metrics?: {
    requests_total: number
    requests_success: number
    requests_failed: number
    avg_latency_ms: number
  }
}

export interface PluginStatusResponse {
  plugins: PluginStatus[]
}

export async function fetchPluginStatus(): Promise<PluginStatusResponse> {
  const { data } = await api.get<PluginStatusResponse>('/agi/plugins/status')
  return data
}
