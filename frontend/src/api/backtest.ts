import { api, adminApi } from './client'

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

export async function fetchQuickBacktest(params: {
  strategy_name: string
  days?: number
}): Promise<unknown> {
  const { data } = await api.get('/backtest/quick', { params })
  return data
}
