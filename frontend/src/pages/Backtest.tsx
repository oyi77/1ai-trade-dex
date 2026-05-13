import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchBacktestStrategies,
  runBacktest,
  fetchBacktestHistory,
} from '../api'

export function Backtest() {
  const [selectedStrategy, setSelectedStrategy] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [initialBankroll, setInitialBankroll] = useState(10000)
  const [strategyParams, setStrategyParams] = useState<Record<string, any>>({})
  const [isRunning, setIsRunning] = useState(false)

  const { data: strategiesResponse } = useQuery({
    queryKey: ['backtest-strategies'],
    queryFn: fetchBacktestStrategies,
  })
  const strategies = useMemo(() => strategiesResponse?.strategies || [], [strategiesResponse?.strategies])

  const { data: history = { runs: [], total: 0 } } = useQuery({
    queryKey: ['backtest-history'],
    queryFn: () => fetchBacktestHistory({ limit: 10 }),
  })

  const queryClient = useQueryClient()

  const runBacktestMutation = useMutation({
    mutationFn: runBacktest,
    onSuccess: () => {
      // Refresh history after successful run
      queryClient.invalidateQueries({ queryKey: ['backtest-history'] })
    },
  })

  const handleRunBacktest = async () => {
    if (!selectedStrategy) return

    setIsRunning(true)
    try {
      await runBacktestMutation.mutateAsync({
        strategy_name: selectedStrategy,
        start_date: startDate,
        end_date: endDate,
        initial_bankroll: initialBankroll,
        params: strategyParams,
      })

    } catch (error) {
      console.error('Backtest failed:', error)
    } finally {
      setIsRunning(false)
    }
  }

  const getDefaultParams = useCallback((strategyName: string) => {
    if (!strategies || !Array.isArray(strategies)) return {}
    const strategy = strategies.find((s: any) => s.name === strategyName)
    return strategy?.default_params || {}
  }, [strategies])

  useEffect(() => {
    if (selectedStrategy) {
      setStrategyParams(getDefaultParams(selectedStrategy))
    }
  }, [getDefaultParams, selectedStrategy])

  return (
    <div className="p-6 space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-neutral-800 rounded-lg p-6"
      >
        <h2 className="text-xl font-bold mb-4">Backtesting Engine</h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Strategy Selection */}
          <div>
            <label className="block text-sm font-medium mb-2">Strategy</label>
            <select
              value={selectedStrategy}
              onChange={(e) => setSelectedStrategy(e.target.value)}
              className="w-full p-2 bg-neutral-700 rounded border border-neutral-600"
            >
              <option value="">Select strategy...</option>
              {strategies && Array.isArray(strategies) && strategies.map((strategy: any) => (
                <option key={strategy.name} value={strategy.name}>
                  {strategy.name} ({strategy.category})
                </option>
              ))}
            </select>
            {selectedStrategy && (
              <p className="mt-2 text-sm text-neutral-400">
                {strategies && Array.isArray(strategies) && strategies.find((s: any) => s.name === selectedStrategy)?.description}
              </p>
            )}
          </div>

          {/* Date Range */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-2">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full p-2 bg-neutral-700 rounded border border-neutral-600"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full p-2 bg-neutral-700 rounded border border-neutral-600"
              />
            </div>
          </div>

          {/* Initial Bankroll */}
          <div>
            <label className="block text-sm font-medium mb-2">Initial Bankroll ($)</label>
            <input
              type="number"
              value={initialBankroll}
              onChange={(e) => setInitialBankroll(Number(e.target.value))}
              className="w-full p-2 bg-neutral-700 rounded border border-neutral-600"
              min="1000"
              step="1000"
            />
          </div>

          {/* Strategy Parameters */}
          <div>
            <label className="block text-sm font-medium mb-2">Strategy Parameters</label>
            <div className="space-y-2 max-h-40 overflow-y-auto">
              {Object.entries(strategyParams).map(([key, value]) => (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-sm w-32">{key}:</span>
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => setStrategyParams(prev => ({
                      ...prev,
                      [key]: e.target.value
                    }))}
                    className="flex-1 p-1 bg-neutral-700 rounded border border-neutral-600 text-sm"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Run Button */}
        <div className="mt-6">
          <button
            onClick={handleRunBacktest}
            disabled={!selectedStrategy || isRunning}
            className="w-full py-2 px-4 bg-green-600 hover:bg-green-700 disabled:bg-green-800 disabled:opacity-50 rounded font-medium transition-colors"
          >
            {isRunning ? 'Running Backtest...' : 'Run Backtest'}
          </button>
        </div>
      </motion.div>

      {/* Look-Ahead Bias Warning */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="bg-amber-900/30 border border-amber-600/40 rounded-lg p-4"
      >
        <div className="flex items-start gap-3">
          <span className="text-amber-400 text-lg">⚠</span>
          <div>
            <h3 className="text-amber-300 font-semibold text-sm">Look-Ahead Bias Warning</h3>
            <p className="text-amber-200/80 text-xs mt-1">
              Backtest results may be inflated if seeded from synthetic data that knows market outcomes before creating signals.
              Use <code className="bg-amber-900/50 px-1 rounded text-amber-300">scripts/seed_honest_backtest.py</code> which fetches
              real historical BTC prices from Binance to eliminate look-ahead bias. Honest-seeded signals are tagged with
              <code className="bg-amber-900/50 px-1 rounded text-amber-300">honest-seed</code> in their reasoning.
            </p>
          </div>
        </div>
      </motion.div>

      {/* Backtest History */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-neutral-800 rounded-lg p-6"
      >
        <h3 className="text-lg font-bold mb-4">Backtest History</h3>
        {history.runs.length === 0 ? (
          <p className="text-neutral-400">No backtest runs yet</p>
        ) : (
          <div className="space-y-4">
            {history.runs.map((run) => (
              <div key={run.id} className="bg-neutral-700 p-4 rounded">
                <div className="flex justify-between items-start">
                  <div>
                    <h4 className="font-medium">{run.strategy_name}</h4>
                    <p className="text-sm text-neutral-400">
                      {new Date(run.start_date).toLocaleDateString()} - {new Date(run.end_date).toLocaleDateString()}
                    </p>
                  </div>
                  {run.completed && (
                    <div className="text-right">
                      <p className="text-green-400 font-semibold">
                        P&L: ${(run.total_pnl ?? 0).toFixed(2)}
                      </p>
                      <p className="text-sm text-neutral-400">
                        Return: {(run.total_return_pct ?? 0).toFixed(2)}%
                      </p>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </motion.div>

      {/* Results Display */}
      <AnimatePresence>
        {runBacktestMutation.data && (
          <motion.div
            key="results"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            transition={{ delay: 0.1 }}
            className="space-y-6"
          >
            {/* Summary Cards */}
            <div className="bg-neutral-800 rounded-lg p-6">
              <h3 className="text-lg font-bold mb-4">
                Results — {runBacktestMutation.data.strategy_name}
                {runBacktestMutation.data.run_id && (
                  <span className="ml-2 text-sm text-neutral-400 font-normal">run #{runBacktestMutation.data.run_id}</span>
                )}
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {(() => {
                  const s = runBacktestMutation.data.results.summary
                  const returnPct = s.total_return_pct ?? 0
                  const winRate = s.win_rate ?? 0
                  return (
                    <>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Total Return</p>
                        <p className={`text-2xl font-bold ${returnPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(2)}%
                        </p>
                        <p className="text-xs text-neutral-500 mt-1">
                          ${(s.initial_bankroll ?? 0).toFixed(0)} → ${(s.final_equity ?? 0).toFixed(0)}
                        </p>
                      </div>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Win Rate</p>
                        <p className="text-2xl font-bold text-blue-400">{(winRate * 100).toFixed(1)}%</p>
                        <p className="text-xs text-neutral-500 mt-1">
                          {s.winning_trades}W / {s.losing_trades}L
                        </p>
                      </div>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Total P&L</p>
                        <p className={`text-2xl font-bold ${(s.total_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {(s.total_pnl ?? 0) >= 0 ? '+' : ''}${(s.total_pnl ?? 0).toFixed(2)}
                        </p>
                        <p className="text-xs text-neutral-500 mt-1">{s.total_trades} trades</p>
                      </div>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Sharpe Ratio</p>
                        <p className="text-2xl font-bold text-amber-400">{s.sharpe_ratio?.toFixed(2) ?? '0.00'}</p>
                        <p className="text-xs text-neutral-500 mt-1">{s.total_signals} signals</p>
                      </div>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Max Drawdown</p>
                        <p className="text-2xl font-bold text-red-400">{((s.max_drawdown ?? 0) * 100).toFixed(1)}%</p>
                        <p className="text-xs text-neutral-500 mt-1">peak-to-trough</p>
                      </div>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Sortino Ratio</p>
                        <p className="text-2xl font-bold text-cyan-400">{s.sortino_ratio?.toFixed(2) ?? '0.00'}</p>
                        <p className="text-xs text-neutral-500 mt-1">downside risk</p>
                      </div>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Profit Factor</p>
                        <p className="text-2xl font-bold text-purple-400">{s.profit_factor?.toFixed(2) ?? '0.00'}</p>
                        <p className="text-xs text-neutral-500 mt-1">gross wins / losses</p>
                      </div>
                      <div className="bg-neutral-700 rounded p-4">
                        <p className="text-xs text-neutral-400 mb-1 uppercase tracking-wide">Avg Edge</p>
                        <p className="text-2xl font-bold text-green-300">{((s.avg_edge ?? 0) * 100).toFixed(1)}%</p>
                        <p className="text-xs text-neutral-500 mt-1">avg trade ${s.avg_trade_size?.toFixed(2) ?? '0.00'}</p>
                      </div>
                    </>
                  )
                })()}
              </div>
            </div>

            {/* Trade Log Table */}
            {runBacktestMutation.data.results.trade_log.length > 0 && (
              <div className="bg-neutral-800 rounded-lg p-6">
                <h3 className="text-lg font-bold mb-4">Trade Log</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-neutral-400 text-xs uppercase tracking-wide border-b border-neutral-700">
                        <th className="pb-2 pr-4">#</th>
                        <th className="pb-2 pr-4">Date</th>
                        <th className="pb-2 pr-4">Market</th>
                        <th className="pb-2 pr-4">Dir</th>
                        <th className="pb-2 pr-4">Entry</th>
                        <th className="pb-2 pr-4">Exit</th>
                        <th className="pb-2 pr-4">Size</th>
                        <th className="pb-2 pr-4">P&L</th>
                        <th className="pb-2 pr-4">Result</th>
                        <th className="pb-2">Bankroll</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-neutral-700">
                      {runBacktestMutation.data.results.trade_log.map((trade, i) => (
                        <tr key={i} className="text-neutral-300 hover:bg-neutral-700/30 transition-colors">
                          <td className="py-2 pr-4 text-neutral-500">{i + 1}</td>
                          <td className="py-2 pr-4 text-xs text-neutral-400">
                            {new Date(trade.timestamp).toLocaleDateString()}
                          </td>
                          <td className="py-2 pr-4 text-xs">{trade.market_ticker ?? '—'}</td>
                          <td className="py-2 pr-4 text-xs">{(trade.direction ?? '?').toUpperCase()}</td>
                          <td className="py-2 pr-4">{((trade.entry_price ?? 0) * 100).toFixed(1)}¢</td>
                          <td className="py-2 pr-4">{trade.exit_price != null ? `${(trade.exit_price * 100).toFixed(1)}¢` : '—'}</td>
                          <td className="py-2 pr-4">${(trade.size ?? 0).toFixed(2)}</td>
                          <td className={`py-2 pr-4 font-semibold ${(trade.pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {(trade.pnl ?? 0) >= 0 ? '+' : ''}${(trade.pnl ?? 0).toFixed(2)}
                          </td>
                          <td className="py-2 pr-4">
                            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                              trade.result === 'win' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
                            }`}>
                              {(trade.result ?? 'unknown').toUpperCase()}
                            </span>
                          </td>
                          <td className="py-2 text-neutral-400">${(trade.bankroll_after_trade ?? 0).toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
