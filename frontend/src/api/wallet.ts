
import { api, adminApi } from './core'

export interface WalletConfigRow {
  id: number
  address: string
  pseudonym: string
  source: string
  tags: string[]
  enabled: boolean
  added_at: string | null
}

export async function fetchWalletConfigs(params?: Record<string, string | number | boolean>): Promise<{ items: WalletConfigRow[]; total: number }> {
  const { data } = await adminApi.get('/wallets/config', { params })
  return data
}

export async function createWalletConfig(body: { address: string; pseudonym?: string; source?: string; tags?: string[]; enabled?: boolean }): Promise<WalletConfigRow> {
  const { data } = await adminApi.post('/wallets/config', body)
  return data
}

export async function updateWalletConfig(id: number, body: Partial<{ pseudonym: string; tags: string[]; enabled: boolean; notes: string }>): Promise<WalletConfigRow> {
  const { data } = await adminApi.put(`/wallets/config/${id}`, body)
  return data
}

export async function deleteWalletConfig(id: number): Promise<void> {
  await adminApi.delete(`/wallets/config/${id}`)
}

export interface CreatedWallet {
  address: string
  private_key: string
  /** WARNING: Save this key securely. Never share or commit to repo. */
}

export async function createWallet(): Promise<CreatedWallet> {
  const { data } = await adminApi.post<CreatedWallet>('/wallets/create')
  return data
}

export interface ActiveWallet {
  active_wallet: string | null
}

export async function getActiveWallet(): Promise<ActiveWallet> {
  const { data } = await api.get<ActiveWallet>('/wallets/active')
  return data
}

export async function setActiveWallet(address: string): Promise<{ active_wallet: string }> {
  const { data } = await adminApi.put<{ active_wallet: string }>('/wallets/active', { address })
  return data
}

export interface WalletBalance {
  address: string
  usdc_balance: number
  last_updated: string | null
  source: 'cache' | 'polymarket' | 'error' | 'none'
  error?: string
}

export async function getWalletBalance(address: string, forceRefresh = false): Promise<WalletBalance> {
  const { data } = await api.get<WalletBalance>(`/wallets/${address}/balance`, {
    params: { force_refresh: forceRefresh }
  })
  return data
}

export async function updateWalletBalance(address: string, balance: number): Promise<WalletBalance> {
  const { data } = await adminApi.put<WalletBalance>(`/wallets/${address}/balance`, {
    usdc_balance: balance,
    last_updated: new Date().toISOString()
  })
  return data
}

// ── Strategies ────────────────────────────────────────────────────────────────

