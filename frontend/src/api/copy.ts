
import { api, adminApi } from './core'

export async function updateCredentials(creds: {
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

export async function fetchCopyTraderStatus(): Promise<{
  enabled: boolean
  tracked_wallets: number
  wallet_details: Array<{ address: string; pseudonym: string; score: number; profit_30d: number }>
  recent_signals: Array<Record<string, unknown>>
  status: string
  errors: Array<{ source: string; message: string }>
}> {
  const { data } = await api.get('/copy/status')
  return data
}

export interface CopyTraderPosition {
  wallet: string
  condition_id: string
  side: string
  size: number
  opened_at: string | null
}

export async function fetchCopyTraderPositions(): Promise<CopyTraderPosition[]> {
  const { data } = await api.get<CopyTraderPosition[]>('/copy/positions')
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

// ── Leaderboard / Whale Tracker ──────────────────────────────────────────────

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

// ── Wallet Config ─────────────────────────────────────────────────────────────

