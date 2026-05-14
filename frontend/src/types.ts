export interface BtcPrice {
  price: number
  change_24h: number
  change_7d: number
  market_cap: number
  volume_24h: number
  last_updated: string
}

export interface Microstructure {
  rsi: number
  momentum_1m: number
  momentum_5m: number
  momentum_15m: number
  vwap_deviation: number
  sma_crossover: number
  volatility: number
  price: number
  source: string
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

export interface Setting {
  id: number
  key: string
  value: string
  description: string | null
  type: string
  created_at: string
  updated_at: string
  updated_by_user_id: string
}

export interface Signal {
  market_ticker: string
  market_title: string
  platform: string
  direction: string
  model_probability: number
  market_probability: number
  edge: number
  confidence: number
  suggested_size: number
  reasoning: string
  timestamp: string
  category: string
  event_slug?: string
  btc_price: number
  btc_change_24h: number
  window_end?: string
  actionable: boolean
  execution_mode?: string
}

export interface Trade {
  id: number
  market_ticker: string
  market_question?: string
  platform: string
  event_slug?: string | null
  direction: string
  entry_price: number
  size: number
  timestamp: string
  settled: boolean
  result: string
  pnl: number | null
  strategy?: string
  signal_source?: string
  confidence?: number
  trading_mode?: string
}

export interface PnlModeStats {
  pnl: number
  realized_pnl?: number
  account_pnl?: number
  bankroll: number
  available_balance?: number
  total_balance?: number
  trades: number
  wins: number
  win_rate: number
  open_exposure?: number
  open_trades?: number
  unrealized_pnl?: number
  position_cost?: number
  position_market_value?: number
  ledger_pnl?: number
  profile_pnl?: number
  profile_traded_count?: number | null
  profile_closed_count?: number | null
  profile_winning_count?: number | null
  profile_open_count?: number | null
  profile_stale_open_count?: number | null
  profile_redeemable_count?: number | null
  profile_open_value?: number | null
  profile_open_initial_value?: number | null
  ledger_trades?: number
  ledger_wins?: number
  ledger_open_trades?: number
  ledger_open_exposure?: number
  initial_bankroll?: number
}

export interface BotStats {
  bankroll: number
  available_balance?: number
  total_balance?: number
  total_trades: number
  winning_trades: number
  win_rate: number
  total_pnl: number
  realized_pnl?: number
  account_pnl?: number
  is_running: boolean
  last_run: string | null
  initial_bankroll: number
  trading_mode?: string
  paper?: PnlModeStats
  testnet?: PnlModeStats
  live?: PnlModeStats
  mode?: string
  active_mode?: string[] | string
  pnl_source?: string
  open_exposure?: number
  open_trades?: number
  settled_trades?: number
  settled_wins?: number
  unrealized_pnl?: number
  position_cost?: number
  position_market_value?: number
  live_ledger_pnl?: number
  live_profile_pnl?: number
  live_profile_traded_count?: number | null
  live_ledger_trades?: number
  live_ledger_wins?: number
  live_profile_closed_count?: number | null
  live_profile_winning_count?: number | null
  live_profile_open_count?: number | null
  live_profile_stale_open_count?: number | null
  live_profile_redeemable_count?: number | null
}

export interface EquityPoint {
  timestamp: string
  pnl: number
  bankroll: number
}

export interface CalibrationSummary {
  total_signals: number
  total_with_outcome: number
  accuracy: number
  avg_predicted_edge: number
  avg_actual_edge: number
  brier_score: number
}

export interface WeatherForecast {
  city_key: string
  city_name: string
  target_date: string
  mean_high: number
  std_high: number
  mean_low: number
  std_low: number
  num_members: number
  ensemble_agreement: number
}

export interface WeatherSignal {
  market_id: string
  city_key: string
  city_name: string
  target_date: string
  threshold_f: number
  metric: string
  direction: string
  model_probability: number
  market_probability: number
  edge: number
  confidence: number
  suggested_size: number
  reasoning: string
  ensemble_mean: number
  ensemble_std: number
  ensemble_members: number
  actionable: boolean
  platform?: string
}

export interface DashboardData {
  stats: BotStats
  btc_price: BtcPrice | null
  microstructure: Microstructure | null
  windows: BtcWindow[]
  active_signals: Signal[]
  recent_trades: Trade[]
  top_winning_trades: Trade[]
  equity_curve: EquityPoint[]
  calibration: CalibrationSummary | null
  weather_signals: WeatherSignal[]
  weather_forecasts: WeatherForecast[]
}

export interface TradeAttemptFactorMap {
  bankroll?: number
  current_exposure?: number
  requested_size?: number
  confidence?: number
  market_ticker?: string
  mode?: string
  [key: string]: string | number | boolean | null | undefined
}

export interface TradeAttempt {
  id: number
  attempt_id: string
  correlation_id: string
  created_at: string | null
  updated_at: string | null
  strategy: string
  mode: string
  market_ticker: string
  platform: string | null
  direction: string | null
  decision: string | null
  status: string
  phase: string
  reason_code: string
  reason: string | null
  confidence: number | null
  edge: number | null
  requested_size: number | null
  adjusted_size: number | null
  entry_price: number | null
  bankroll: number | null
  current_exposure: number | null
  risk_allowed: boolean | null
  risk_reason: string | null
  trade_id: number | null
  order_id: string | null
  latency_ms: number | null
  factors: TradeAttemptFactorMap | string | null
  decision_data: Record<string, unknown> | string | null
  signal_data: Record<string, unknown> | string | null
}

export interface TradeAttemptsResponse {
  items: TradeAttempt[]
  total: number
}

export interface TradeAttemptSummaryBucket {
  status?: string
  mode?: string
  reason_code?: string
  count: number
}

export interface TradeAttemptSummary {
  total: number
  executed: number
  blocked: number
  execution_rate: number
  last_attempt_at: string | null
  by_status: TradeAttemptSummaryBucket[]
  by_mode: TradeAttemptSummaryBucket[]
  top_blockers: TradeAttemptSummaryBucket[]
  recent_blockers: TradeAttempt[]
}

export interface WalletConfig {
  id: number
  address: string
  pseudonym: string
  source: string
  tags: string[]
  enabled: boolean
  added_at: string | null
}

export interface CreatedWallet {
  address: string
  message: string
}

export interface WalletBalance {
  address: string
  usdc_balance: number
  last_updated: string | null
  source: string
}

export interface SyncModeStatus {
  last_synced_at: string | null
  next_sync_at: string | null
  last_result: string | null
  status: string
}

export interface SyncStatus {
  testnet: SyncModeStatus
  live: SyncModeStatus
}

export interface KanbanCard {
  id: string
  name: string
  strategy_name: string
  status: string
  column: string
  backtest_passed: boolean
  backtest_sharpe: number | null
  backtest_win_rate: number | null
  shadow_trades: number | null
  shadow_win_rate: number | null
  shadow_pnl: number | null
  degradation_count: number
  review_reason: string | null
  created_at: string | null
  promoted_at: string | null
  retired_at: string | null
}

export interface KanbanColumn {
  id: string
  label: string
  order: number
  cards: KanbanCard[]
}

export interface KanbanBoard {
  columns: KanbanColumn[]
  total_experiments: number
}
