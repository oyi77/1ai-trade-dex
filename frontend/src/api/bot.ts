import { api, adminApi } from './client'

export async function fetchBotState(): Promise<{
  trading_mode: string
  active_modes: string[]
  bot_running: boolean
  uptime_seconds: number
  pending_trades: number
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

export async function startBot(): Promise<{ status: string; is_running: boolean }> {
  const { data } = await adminApi.post('/bot/start')
  return data
}

export async function stopBot(): Promise<{ status: string; is_running: boolean }> {
  const { data } = await adminApi.post('/bot/stop')
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

export async function liveAdjust(params: { action: string; value?: number }): Promise<{ status: string; message: string }> {
  const { data } = await adminApi.post('/bot/live-adjust', params)
  return data
}
