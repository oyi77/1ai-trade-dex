import type {
  JournalEntry, JournalStats, EvalReportsResponse, EvalReportDetail,
} from '../types'
import { api, adminApi } from './core'

export interface TradingWallet {
  id: number
  label: string
  chain: string
  address: string
  has_private_key: boolean
  api_key: string | null
  has_api_secret: boolean
  enabled: boolean
  is_paper: boolean
  created_at: string
  notes: string | null
}

export interface WalletAllocation {
  id: number
  wallet_id: number
  strategy_name: string
  weight: number
  max_exposure_usd: number | null
  enabled: boolean
}

export interface CopyPolicy {
  id: number
  source_name: string
  enabled: boolean
  max_size_usd: number
  confidence_floor: number
  max_delay_seconds: number
  size_scale_factor: number
  cooldown_seconds: number
}

export async function fetchTradingWallets(): Promise<{items: TradingWallet[]}> {
  const { data } = await api.get('/wallet-allocations/wallets')
  return data
}

export async function createTradingWallet(payload: Partial<TradingWallet>): Promise<TradingWallet> {
  const { data } = await api.post('/wallet-allocations/wallets', payload)
  return data
}

export async function updateTradingWallet(id: number, payload: Partial<TradingWallet>): Promise<TradingWallet> {
  const { data } = await api.put(`/wallet-allocations/wallets/${id}`, payload)
  return data
}

export async function fetchWalletAllocations(): Promise<{items: WalletAllocation[]}> {
  const { data } = await adminApi.get('/wallet-allocations/allocations')
  return data
}

export async function createWalletAllocation(payload: Partial<WalletAllocation>): Promise<WalletAllocation> {
  const { data } = await adminApi.post('/wallet-allocations/allocations', payload)
  return data
}

export async function updateWalletAllocation(id: number, payload: Partial<WalletAllocation>): Promise<WalletAllocation> {
  const { data } = await adminApi.put(`/wallet-allocations/allocations/${id}`, payload)
  return data
}

export async function fetchCopyPolicies(): Promise<{items: CopyPolicy[]}> {
  const { data } = await api.get('/copy-policy/')
  return data
}

export async function createCopyPolicy(payload: Partial<CopyPolicy>): Promise<CopyPolicy> {
  const { data } = await api.post('/copy-policy/', payload)
  return data
}

export async function updateCopyPolicy(id: number, payload: Partial<CopyPolicy>): Promise<CopyPolicy> {
  const { data } = await api.put(`/copy-policy/${id}`, payload)
  return data
}

// ── Trading Journal ────────────────────────────────────────────────────────

export async function fetchJournal(params: {
  page?: number
  page_size?: number
  strategy?: string
  mode?: string
  result?: string
  market_type?: string
  date_from?: string
  date_to?: string
  sort_by?: string
  sort_dir?: string
}): Promise<{ entries: JournalEntry[]; total: number; page: number; page_size: number }> {
  const { data } = await adminApi.get('/journal', { params })
  return data
}

export async function fetchJournalStats(params?: {
  strategy?: string
  mode?: string
  days?: number
}): Promise<JournalStats> {
  const { data } = await adminApi.get('/journal/stats', { params })
  return data
}

export async function updateJournalNotes(
  tradeId: number,
  notes: string,
  tags: string[] = []
): Promise<void> {
  await adminApi.put(`/journal/${tradeId}/notes`, { notes, tags })
}

// ── Eval Reports ────────────────────────────────────────────────────────────

export async function fetchEvalReports(): Promise<EvalReportsResponse> {
  const { data } = await api.get<EvalReportsResponse>('/evals/reports')
  return data
}

export async function fetchEvalReport(filename: string): Promise<EvalReportDetail> {
  const { data } = await api.get<EvalReportDetail>(`/evals/reports/${encodeURIComponent(filename)}`)
  return data
}

export interface MakerTakerRoleStats {
  count: number
  pnl: number
  size: number
  roi: number
}

export interface MakerTakerStats {
  maker: MakerTakerRoleStats
  taker: MakerTakerRoleStats
  recommendation: 'prefer_maker' | 'reduce_taker' | 'neutral' | 'insufficient_data'
  cached_at: string
}

export async function fetchMakerTakerStats(): Promise<MakerTakerStats> {
  const { data } = await api.get<MakerTakerStats>('/analytics/maker-taker')
  return data
}
