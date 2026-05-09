<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# frontend/src/components/dashboard

## Purpose
Dashboard tab components rendered inside the main Dashboard page. Each tab provides a different lens on trading activity: system overview with key stats, market listing and selection, active trading signals, executed trade history with PnL, performance metrics and equity curve, decision log with reasoning, and strategy leaderboard.

## Key Files

| File | Description |
|------|-------------|
| `OverviewTab.tsx` | Dashboard overview — displays summary stats (total return, Sharpe ratio, win rate, max drawdown), active window info, quick stats cards |
| `MarketsTab.tsx` | Market listing — paginated Polymarket markets table with question, yes/no prices, volume; sortable columns; 60s refetch interval |
| `SignalsTab.tsx` | Trading signals — unified view of BTC oracle signals and weather-based signals with sorting by edge/probability/size, simulate trade button |
| `TradesTab.tsx` | Trade history — paginated table of executed trades showing ticker, direction, entry/exit price, PnL, timestamp; sortable and filterable |
| `PerformanceTab.tsx` | Performance metrics — EquityChart showing P&L over time, Sharpe ratio, cumulative return, drawdown analysis |
| `DecisionsTab.tsx` | Decision log — displays AI reasoning behind signals and trades, model confidence, market analysis notes |
| `LeaderboardTab.tsx` | Strategy leaderboard — ranks strategies by returns, Sharpe, win rate; tracks performance over different time periods |
| `KanbanTab.tsx` | Kanban board interface — visual workflow management for trade proposals and approvals |
| `WhaleTrackerTab.tsx` | Whale tracking dashboard — monitors large trader positions and market impact |
| `SettlementsTab.tsx` | Market settlements — tracks pending and completed market settlements and payouts |
| `MarketIntelTab.tsx` | Market intelligence — comprehensive market analysis and research insights |
| `DecisionLogTab.tsx` | Detailed decision log — chronological view of AI decisions with full context |
| `ControlRoomTab.tsx` | System control center — real-time monitoring and manual override capabilities |
| `SystemEfficiencyPanel.tsx` | System efficiency metrics — tracks resource usage, latency, and performance indicators |
| `SelfImprovementMetrics.tsx` | AGI self-improvement metrics — displays learning progress and model accuracy |
| `EdgeTrackerTab.tsx` | Edge tracking — monitors market inefficiencies and arbitrage opportunities |
| `ProfitCurveChart.tsx` | Profit visualization — displays profit curves and risk/reward analysis |
| `TradingTerminalTab.tsx` | Trading terminal — advanced trading interface with real-time execution |

## Subdirectories
None — all dashboard components are at root level of `dashboard/`.

## For AI Agents

### Working In This Directory
- Each tab is independently mountable — components don't share state with other tabs
- Data fetching via React Query — use appropriate refetch intervals (signals 30s, markets 60s, trades real-time via WebSocket)
- Lazy load charts and heavy components using React.lazy() + Suspense
- Use `useStats()` hook for general dashboard stats (called by OverviewTab)
- Use `useTableQuery()` hook for paginated table data (used by MarketsTab, TradesTab)
- Use `useTradeEvents()` hook for real-time trade updates
- Handle empty/loading states gracefully — show placeholder tables or "No data" message
- All times shown in user's local timezone — use date-fns for formatting

### Testing Requirements
- Mock all dashboard API endpoints via fixtures in `test/mocks.ts`
- Test pagination: next/prev page, page size changes
- Test sorting: click column header, verify data order changes
- Test filtering: apply filter, verify results filtered
- Test real-time updates: simulate WebSocket message, verify UI updates
- Test empty states: zero trades, zero signals, no markets
- Test error states: API failure, empty response
- Use React Testing Library to query by role (table, heading) and text

### Common Patterns
- OverviewTab: uses `useStats()` hook + StatsCards component for quick summary
- MarketsTab: fetches markets list, renders as paginated table, refetches every 60s
- SignalsTab: calls useQuery to fetch signals, aggregates BTC + weather signals, displays with sorting
- TradesTab: uses DataTable with useTableQuery for pagination and sorting
- PerformanceTab: renders EquityChart component with historical P&L data
- All tabs show loading spinner during initial fetch
- All tabs handle errors with fallback message and retry button

## Dependencies

### Internal
- `../../api.ts` — fetchSignals, fetchTrades, fetchMarkets, fetchSignalHistory, fetchPerformance, fetchLeaderboard functions
- `../../types.ts` — Signal, Trade, BotStats, EquityPoint, WeatherSignal, PolymarketMarket interfaces
- `../../hooks/useStats.ts` — bot stats polling (used by OverviewTab)
- `../../hooks/useTableQuery.ts` — paginated table data with sorting/filtering (used by MarketsTab, TradesTab)
- `../../hooks/useTradeEvents.ts` — real-time trade event streaming
- `../DataTable.tsx` — reusable table component
- `../EquityChart.tsx` — charting component for PerformanceTab
- `../SignalsTable.tsx` — signal display component
- `../TradesTable.tsx` — trade display component
- `../StatsCards.tsx` — stat card display component

### External
- `react@18` — useState, useEffect, Suspense, lazy
- `@tanstack/react-query@5` — useQuery for data fetching
- `framer-motion@10` — animations
- `recharts@2` — charts (via EquityChart)
- `date-fns@3` — date formatting
- `tailwindcss@3` — styling and layout

<!-- MANUAL: -->
