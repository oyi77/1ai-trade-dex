import axios from 'axios'
import type { DashboardData, Signal, Trade, BotStats, BtcPrice, BtcWindow, WeatherForecast, WeatherSignal, Setting, TradeAttemptSummary, TradeAttemptsResponse, KanbanBoard, KanbanCard } from './types'
import { getCsrfToken, getLegacyApiKey } from './utils/auth'

const getApiBase = () => {
  const env = import.meta.env.VITE_API_URL
  if (env && env !== 'undefined') {
    const isEnvLocal = env.includes('localhost') || env.includes('127.0.0.1')
    const isPageLocal = window.location.hostname.includes('localhost') || window.location.hostname.includes('127.0.0.1')
    
    if (isEnvLocal && !isPageLocal) {
      return ''
    }
    return env
  }
  return ''
}
export const API_BASE = getApiBase()

const API_TIMEOUT = Number(import.meta.env.VITE_API_TIMEOUT_MS) || 15000

/**
 * Build a WebSocket URL for the given path.
 * In production with VITE_API_URL set, converts http(s) to ws(s).
 * In dev (no VITE_API_URL), uses current page host with protocol detection.
 */
export function getWsUrl(path: string): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, 'ws') + path
  }
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}${path}`
}

export const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: API_TIMEOUT,
})

export const adminApi = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: API_TIMEOUT,
})

adminApi.interceptors.request.use(config => {
  const csrf = getCsrfToken()
  if (csrf) {
    config.headers = config.headers ?? {}
    config.headers['X-CSRF-Token'] = csrf
  }
  const legacy = getLegacyApiKey()
  if (legacy && !csrf) {
    config.headers = config.headers ?? {}
    config.headers['Authorization'] = `Bearer ${legacy}`
  }
  config.withCredentials = true
  return config
})

export function getAdminApiKey(): string {
  return getCsrfToken() || getLegacyApiKey()
}

export function setAdminApiKey(key: string) {
  if (key) localStorage.setItem('adminApiKey', key)
  else localStorage.removeItem('adminApiKey')
}

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

export async function fetchBacktestStrategies(): Promise<{
  strategies: Array<{
    name: string
    description: string
    category: string
    default_params: Record<string, any>
  }>
}> {
  const { data } = await api.get('/backtest/strategies')
  return data
}

export async function fetchBacktestHistory(params?: {
  limit?: number
  offset?: number
}): Promise<{
  runs: Array<any>
  total: number
  limit: number
  offset: number
}> {
  const { data } = await api.get('/backtest/history', { params })
  return data
}

export async function runBacktest(config: {
  strategy_name: string
  start_date?: string
  end_date?: string
  initial_bankroll?: number
  params?: Record<string, any>
}): Promise<{
  strategy_name: string
  start_date: string
  end_date: string
  initial_bankroll: number
  results: {
    summary: {
      total_signals: number
      total_trades: number
      winning_trades: number
      losing_trades: number
      win_rate: number
      initial_bankroll: number
      final_equity: number
      total_pnl: number
      total_return_pct: number
      sharpe_ratio: number
      max_drawdown: number
      sortino_ratio: number
      profit_factor: number
      avg_edge: number
      avg_trade_size: number
    }
    trade_log: Array<{
      entry_price: number
      exit_price: number | null
      size: number
      pnl: number
      result: string
      timestamp: string
      market_ticker: string
      direction: string
      edge_at_entry: number
      bankroll_after_trade: number
    }>
    equity_curve: Array<{
      timestamp: string
      bankroll: number
    }>
    signals_processed: number
  }
  run_id?: number
}> {
  const { data } = await adminApi.post('/backtest/run', config)
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
  const { data } = await api.get('/wallets/config', { params })
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

export interface StrategyConfig {
  name: string
  description: string
  category: string
  enabled: boolean
  interval_seconds: number
  params: Record<string, unknown>
  default_params: Record<string, unknown>
  updated_at: string | null
  required_credentials?: string[]
}

export async function fetchStrategies(): Promise<StrategyConfig[]> {
  const { data } = await api.get('/strategies')
  return data
}

export async function updateStrategy(name: string, body: { enabled?: boolean; interval_seconds?: number; params?: Record<string, unknown>; trading_mode?: string | null }): Promise<StrategyConfig> {
  const { data } = await adminApi.put(`/strategies/${name}`, body)
  return data
}

export async function runStrategyNow(name: string): Promise<{ status: string }> {
  const { data } = await adminApi.post(`/strategies/${name}/run-now`)
  return data
}

// ── Market Watch ──────────────────────────────────────────────────────────────

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

// ── Decision Log ──────────────────────────────────────────────────────────────

export interface DecisionLogRow {
  id: number
  strategy: string
  market_ticker: string
  decision: string
  confidence: number | null
  reason: string | null
  outcome: string | null
  created_at: string | null
  signal_data?: Record<string, unknown> | null
}

export interface DecisionLogDetail extends DecisionLogRow {
  signal_data: Record<string, unknown> | null
}

export async function fetchDecisions(params?: Record<string, string | number>): Promise<{ items: DecisionLogRow[]; total: number }> {
  const { data } = await api.get('/decisions', { params })
  return data
}

export async function fetchDecision(id: number): Promise<DecisionLogDetail> {
  const { data } = await api.get(`/decisions/${id}`)
  return data
}

export function decisionsExportUrl(params?: Record<string, string>): string {
  const qs = params ? '?' + new URLSearchParams(params).toString() : ''
  return `${API_BASE}/api/v1/decisions/export${qs}`
}

// ── Health ────────────────────────────────────────────────────────────────────

export interface StrategyHealth {
  name: string
  last_heartbeat: string | null
  lag_seconds: number | null
  healthy: boolean
}

export async function fetchHealth(): Promise<{ strategies: StrategyHealth[]; bot_running: boolean }> {
  const { data } = await api.get('/health/ready')
  return data
}

// ── Signal Config (public, no auth) ────────────────────────────────────────────

export interface SignalConfig {
  approval_mode: 'manual' | 'auto_approve' | 'auto_deny'
  min_confidence: number
  notification_duration_ms: number
}

export async function fetchSignalConfig(): Promise<SignalConfig> {
  const { data } = await api.get('/signal-config')
  return data
}

// ── AI Suggest ────────────────────────────────────────────────────────────────

export async function fetchAISuggest(): Promise<{
  status: string
  suggestions: Record<string, number | null>
  analysis: Record<string, unknown>
  ai_provider: string
  raw_response?: string
}> {
  const { data } = await api.get('/admin/ai/suggest')
  return data
}

// ============================================================================
// PE-011 Phase 2 endpoints — auto-trader pending approvals
// ============================================================================

export interface PendingApproval {
  id: number
  market_id: string
  direction: string
  size: number
  confidence: number
  signal_data: Record<string, unknown> | null
  status: string
  created_at: string | null
}

export async function fetchPendingApprovals(): Promise<PendingApproval[]> {
  const { data } = await api.get<PendingApproval[]>('/auto-trader/pending')
  return data
}

export async function approvePendingTrade(id: number): Promise<{ id: number; status: string }> {
  const { data } = await adminApi.post<{ id: number; status: string }>(`/auto-trader/approve/${id}`)
  return data
}

export async function rejectPendingTrade(id: number): Promise<{ id: number; status: string }> {
  const { data } = await adminApi.post<{ id: number; status: string }>(`/auto-trader/reject/${id}`)
  return data
}

export async function batchApprovePendingTrades(ids: number[]): Promise<{ approved_count: number; approved_ids: number[] }> {
  const { data } = await adminApi.post<{ approved_count: number; approved_ids: number[] }>('/auto-trader/batch-approve', { trade_ids: ids })
  return data
}

export async function batchRejectPendingTrades(ids: number[]): Promise<{ rejected_count: number; rejected_ids: number[] }> {
  const { data } = await adminApi.post<{ rejected_count: number; rejected_ids: number[] }>('/auto-trader/batch-reject', { trade_ids: ids })
  return data
}

export async function clearAllPendingTrades(): Promise<{ cleared_count: number; cleared_ids: number[] }> {
  const { data } = await adminApi.post<{ cleared_count: number; cleared_ids: number[] }>('/auto-trader/clear-all')
  return data
}

export interface WhaleTx {
  id: number
  tx_hash: string
  wallet: string
  market_id: string | null
  side: string | null
  size_usd: number
  observed_at: string | null
}

export async function fetchWhaleTransactions(limit = 50): Promise<WhaleTx[]> {
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

// ── Strategy P&L ─────────────────────────────────────────────────────────────────

export interface StrategyPnL {
  strategy: string
  total_trades: number
  wins: number
  losses: number
  pending: number
  win_rate: number
  total_pnl: number
  avg_edge: number
  avg_size: number
}

export async function fetchStrategyStats(): Promise<{ strategies: StrategyPnL[] }> {
  const { data } = await api.get('/stats/strategies')
  return data
}

// ── Edge Performance (Parallel Edge Discovery) ───────────────────────────────────

export interface EdgePerformanceTrack {
  track_name: string
  total_signals: number
  signals_executed: number
  winning_trades: number
  win_rate: number
  total_pnl: number
  trade_count: number
  status: string
}

export interface EdgePerformanceResponse {
  tracks: EdgePerformanceTrack[]
  days: number
  since_date: string
}

export async function fetchEdgePerformance(days = 7): Promise<EdgePerformanceResponse> {
  const { data } = await api.get<EdgePerformanceResponse>('/edge-performance', { params: { days } })
  return data
}

// ── Sync Status ──────────────────────────────────────────────────────────────

export async function getSyncStatus(): Promise<import('./types').SyncStatus> {
  const { data } = await adminApi.get<import('./types').SyncStatus>('/admin/sync-status')
  return data
}

export async function triggerManualSync(mode: 'testnet' | 'live'): Promise<{ status: string; message: string }> {
  const { data } = await adminApi.post<{ status: string; message: string }>('/admin/sync-now', null, {
    params: { mode }
  })
  return data}

// ── MiroFish Service Management ────────────────────────────────────────────

export interface MiroFishServiceStatus {
  state: 'running' | 'paused' | 'stopped'
  started_at: string | null
  uptime_seconds: number | null
  last_signal_fetch: string | null
  total_signals_fetched: number
  error_message: string | null
  monitor: {
    health_status: string
    latency_ms: number
    error_rate: number
    circuit_breaker_state: string
    total_requests: number
    failed_requests: number
    consecutive_failures: number
    last_success_time: string | null
    last_failure_time: string | null
    circuit_breaker_config?: Record<string, unknown>
  }
}

export interface MiroFishServiceAction {
  success: boolean
  message: string
  state: string
  data?: MiroFishServiceStatus
}

export async function fetchMiroFishStatus(): Promise<MiroFishServiceStatus> {
  const { data } = await api.get<MiroFishServiceStatus>('/settings/mirofish/status')
  return data
}

export async function mirofishStart(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/start')
  return data
}

export async function mirofishStop(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/stop')
  return data
}

export async function mirofishPause(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/pause')
  return data
}

export async function mirofishRestart(): Promise<MiroFishServiceAction> {
  const { data } = await adminApi.post<MiroFishServiceAction>('/settings/mirofish/restart')
  return data
}

// ── MiroFish Process Management ────────────────────────────────────────────

export interface MiroFishProcessStatus {
  backend_running: boolean
  backend_pid: number | null
  frontend_running: boolean
  frontend_pid: number | null
}

export interface MiroFishProcessAction {
  success: boolean
  results: { backend: string; frontend: string }
}

export async function fetchMiroFishProcesses(): Promise<MiroFishProcessStatus> {
  const { data } = await adminApi.get<MiroFishProcessStatus>('/settings/mirofish/processes')
  return data
}

export async function startMiroFishProcesses(): Promise<MiroFishProcessAction> {
  const { data } = await adminApi.post<MiroFishProcessAction>('/settings/mirofish/processes/start')
  return data
}

export async function stopMiroFishProcesses(): Promise<MiroFishProcessAction> {
  const { data } = await adminApi.post<MiroFishProcessAction>('/settings/mirofish/processes/stop')
  return data
}

export async function restartMiroFishProcesses(): Promise<MiroFishProcessAction> {
  const { data } = await adminApi.post<MiroFishProcessAction>('/settings/mirofish/processes/restart')
  return data
}

export async function fetchKanbanBoard(): Promise<KanbanBoard> {
  const { data } = await api.get<KanbanBoard>('/agi/kanban')
  return data
}

export async function moveKanbanCard(experimentId: number, targetStatus: string, reason?: string): Promise<{ id: string; old_status: string; new_status: string; card: KanbanCard }> {
  const { data } = await adminApi.post(`/agi/kanban/${experimentId}/move`, { target_status: targetStatus, reason: reason ?? null })
  return data
}

// ── Plugin System ────────────────────────────────────────────────────────────

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

// ── Venue Monitor ────────────────────────────────────────────────────────────

export interface VenueMetric {
  name: string
  value: number | string
  trend?: 'up' | 'down' | 'neutral'
  change?: number
}

export interface VenueStatus {
  venue: string
  connected: boolean
  last_seen: string
  metrics: VenueMetric[]
  status: 'healthy' | 'warning' | 'error'
  latency_ms: number
  issues?: string[]
}

export interface VenueDataResponse {
  venues: VenueStatus[]
}

export async function fetchVenueData(): Promise<VenueDataResponse> {
  const { data } = await api.get<VenueDataResponse>('/agi/venue/status')
  return data
}

// ── AGI Sandbox ──────────────────────────────────────────────────────────────

export interface SandboxScenario {
  name: string
  description: string
}

export interface SandboxValidationResult {
  run_id: string
  timestamp: string
  scenario: string
  status: 'pending' | 'validating' | 'completed' | 'failed'
  result?: {
    success: boolean
    message?: string
    errors?: string[]
    warnings?: string[]
    metrics?: {
      validation_time_ms: number
      lines_of_code: number
      gate_passed: number
      total_gates: number
    }
  }
}

export interface SandboxResponse {
  scenarios: SandboxScenario[]
  results: SandboxValidationResult[]
}

export async function fetchSandboxScenarios(): Promise<SandboxResponse> {
  const { data } = await api.get<SandboxResponse>('/agi/sandbox/scenarios')
  return data
}

export async function fetchSandboxResults(): Promise<SandboxResponse> {
  const { data } = await api.get<SandboxResponse>('/agi/sandbox/results')
  return data
}

// ── AGI Graphs ───────────────────────────────────────────────────────────────

export interface AGIGraphNode {
  id: string
  label: string
  type: string
  status: string
  data?: any
}

export interface AGIGraphEdge {
  source: string
  target: string
  label?: string
}

export interface AGIGraph {
  name: string
  nodes: AGIGraphNode[]
  edges: AGIGraphEdge[]
}

export interface AGIRunResult {
  run_id: string
  graph_name: string
  timestamp: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: {
    success: boolean
    data?: any
    errors?: string[]
  }
}

export interface AGIGraphsResponse {
  graphs: AGIGraph[]
}

export interface AGIRunResultsResponse {
  results: AGIRunResult[]
}

export async function fetchAGIGraphs(): Promise<AGIGraphsResponse> {
  const { data } = await api.get<AGIGraphsResponse>('/agi/graphs')
  return data
}

export async function fetchAGIRunResult(): Promise<AGIRunResultsResponse> {
  const { data } = await api.get<AGIRunResultsResponse>('/agi/graphs/runs')
  return data
}

// --- Multi-Wallet & Copy-Trade API ---
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
  const { data } = await api.get('/wallet-allocations/allocations')
  return data
}

export async function createWalletAllocation(payload: Partial<WalletAllocation>): Promise<WalletAllocation> {
  const { data } = await api.post('/wallet-allocations/allocations', payload)
  return data
}

export async function updateWalletAllocation(id: number, payload: Partial<WalletAllocation>): Promise<WalletAllocation> {
  const { data } = await api.put(`/wallet-allocations/allocations/${id}`, payload)
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
