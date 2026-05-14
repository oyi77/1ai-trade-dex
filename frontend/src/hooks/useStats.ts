import { POLL } from '../polling'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { BotStats } from '../types'

import { getWsUrl } from '../api'

export function useStats() {
  const [wsStats, setWsStats] = useState<BotStats | null>(null)

  useEffect(() => {
    let ws: WebSocket | null = null
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      const wsUrl = getWsUrl('/ws/dashboard-data')
      ws = new WebSocket(wsUrl)
      
      ws.onopen = () => {
        try {
          ws?.send(JSON.stringify({ action: 'subscribe', topic: 'stats' }))
        } catch (e) {
          console.error('Failed to subscribe to dashboard stats WebSocket:', e)
        }
      }
      
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'stats_update' && msg.data) {
            setWsStats(msg.data)
          }
        } catch (e) {
          console.error('Failed to parse stats WebSocket message:', e)
        }
      }
      
      ws.onerror = () => {}
      
      ws.onclose = () => {
        reconnectTimeout = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      if (reconnectTimeout) clearTimeout(reconnectTimeout)
      if (ws) {
        ws.onclose = null
        ws.close()
      }
    }
  }, [])

  const { data: fallbackData, isLoading, error } = useQuery({
    queryKey: ['stats-unified'],
    queryFn: async () => {
      const { fetchDashboard } = await import('../api')
      const dashboard = await fetchDashboard()
      return dashboard.stats
    },
    refetchInterval: wsStats ? false : POLL.NORMAL,
  })

  const stats = wsStats || fallbackData || ({
    is_running: false,
    last_run: null,
    total_trades: 0,
    total_pnl: 0,
    realized_pnl: 0,
    account_pnl: 0,
    bankroll: 10000,
    available_balance: 10000,
    total_balance: 10000,
    winning_trades: 0,
    win_rate: 0,
    initial_bankroll: 10000,
    mode: 'paper',
    paper: { pnl: 0, realized_pnl: 0, account_pnl: 0, bankroll: 10000, available_balance: 10000, total_balance: 10000, trades: 0, wins: 0, win_rate: 0 },
    testnet: { pnl: 0, realized_pnl: 0, account_pnl: 0, bankroll: 0, available_balance: 0, total_balance: 0, trades: 0, wins: 0, win_rate: 0 },
    live: { pnl: 0, realized_pnl: 0, account_pnl: 0, bankroll: 0, available_balance: 0, total_balance: 0, trades: 0, wins: 0, win_rate: 0 },
  } as BotStats)

  // Use mode-specific stats when available (paper/testnet/live split)
  const active = stats.mode === 'all' ? null
    : stats.mode === 'live' && stats.live
    ? stats.live
    : stats.mode === 'testnet' && stats.testnet
      ? stats.testnet
      : stats.paper || null

  const settledPnl = active ? active.pnl : stats.total_pnl
  const wins = active ? active.wins : stats.winning_trades
  const trades = active ? active.trades : stats.total_trades
  const bankroll = active ? active.bankroll : stats.bankroll
  const initialBankroll = active?.initial_bankroll ?? stats.initial_bankroll ?? 10000
  const totalPnl = active?.account_pnl ?? stats.account_pnl ?? settledPnl
  const realizedPnl = active?.realized_pnl ?? stats.realized_pnl ?? settledPnl
  const availableBalance = active?.available_balance ?? stats.available_balance ?? bankroll
  const totalBalance = active?.total_balance ?? stats.total_balance ?? bankroll
  const modeSplits = [stats.paper, stats.testnet, stats.live].filter((mode): mode is NonNullable<typeof mode> => Boolean(mode))
  const aggregateOpenTrades = modeSplits.reduce((sum, mode) => sum + (mode.open_trades ?? 0), 0)
  const aggregateOpenExposure = modeSplits.reduce((sum, mode) => sum + (mode.open_exposure ?? 0), 0)
  const openTrades = stats.mode === 'all' && aggregateOpenTrades > 0
    ? aggregateOpenTrades
    : stats.open_trades ?? aggregateOpenTrades
  const openExposure = stats.mode === 'all' && aggregateOpenExposure > 0
    ? aggregateOpenExposure
    : stats.open_exposure ?? aggregateOpenExposure

  return {
    stats,
    isLoading,
    error,

    pnl: totalPnl,
    realizedPnl,
    settledPnl,
    wins,
    trades,
    bankroll,
    availableBalance,
    totalBalance,
    winRate: active ? (active.win_rate * 100) : (stats.win_rate * 100),
    returnPercent: initialBankroll > 0 ? (totalPnl / initialBankroll * 100) : 0,
    isRunning: stats.is_running,
    lastRun: stats.last_run,
    mode: stats.mode,
    openExposure,
    openTrades,
    settledTrades: stats.settled_trades ?? 0,
    settledWins: stats.settled_wins ?? 0,
    unrealizedPnl: stats.unrealized_pnl ?? 0,
    positionCost: stats.position_cost ?? 0,
    positionMarketValue: stats.position_market_value ?? 0,
    totalEquity: totalBalance,

    // Paper/Testnet/Live specific
    paperStats: stats.paper,
    testnetStats: stats.testnet,
    liveStats: stats.live,
  }
}
