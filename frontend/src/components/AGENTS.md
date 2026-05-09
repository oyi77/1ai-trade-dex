<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# frontend/src/components

## Purpose
Reusable React UI components — shared primitives, domain-specific panels, and feature-area sub-directories. Components here are consumed by pages in `src/pages/` and should not contain page-level routing logic.

## Key Files

| File | Description |
|------|-------------|
| `NavBar.tsx` | Top navigation bar with mode indicator and admin controls |
| `StatsCards.tsx` | Summary stat cards — bankroll, PnL, win rate, trade count |
| `TradesTable.tsx` | Paginated trades table with filtering |
| `SignalsTable.tsx` | Active signals display |
| `EquityChart.tsx` | Equity curve chart (Recharts) |
| `EdgeDistribution.tsx` | Edge distribution histogram |
| `ActivityTimeline.tsx` | Strategy activity timeline |
| `WhaleActivityFeed.tsx` | Real-time whale wallet activity feed |
| `LiveMarketView.tsx` | Live market price and order book view |
| `OpportunityScanner.tsx` | Market opportunity scanner results |
| `ProposalApprovalPanel.tsx` | Strategy proposal review and approval UI |
| `ProposalApprovalUI.tsx` | Proposal approval action buttons |
| `CalibrationPanel.tsx` | Probability calibration metrics panel |
| `MicrostructurePanel.tsx` | Market microstructure analysis panel |
| `BrainGraph.tsx` | AI decision graph visualization |
| `GlobeView.tsx` | Geographic market activity globe |
| `WeatherPanel.tsx` | Weather market signals panel |
| `Terminal.tsx` | Command terminal for admin actions |
| `TradeNotifications.tsx` | Real-time trade notification toasts |
| `DataTable.tsx` | Generic sortable/filterable data table primitive |
| `FilterBar.tsx` | Reusable filter bar component |
| `Skeleton.tsx` | Loading skeleton placeholder |
| `PageLoader.tsx` | Full-page loading state |
| `ErrorBoundary.tsx` | React error boundary — catches render errors |
| `LoginModal.tsx` | Admin login modal |
| `AdminOnly.tsx` | Wrapper that hides children from non-admin users |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `admin/` | Admin panel tab components — strategy config, credentials, risk, AGI controls (see `hft/AGENTS.md` for pattern) |
| `dashboard/` | Dashboard tab components — overview, trades, signals, performance, markets |
| `hft/` | HFT monitoring components — strategy toggles, signal feed, metrics (see `hft/AGENTS.md`) |
| `__tests__/` | Component unit tests |

## For AI Agents

### Working In This Directory
- **Components must not fetch data directly with `useEffect` + `fetch`** — use `useQuery` from `@tanstack/react-query` with `POLL.*` intervals from `src/polling.ts`.
- **`AdminOnly` wraps any UI that should be hidden from non-admin sessions** — use it for destructive actions, credential displays, and strategy controls.
- **`ErrorBoundary` wraps page-level components** — do not remove it from page wrappers; it prevents a single component crash from taking down the whole dashboard.
- Export new components from the nearest `index.tsx` if one exists in the subdirectory.
- Use `DataTable` and `FilterBar` primitives rather than reimplementing table/filter logic per component.

### Testing Requirements
- Component tests live in `__tests__/` (co-located) or `src/test/`
- Use `@testing-library/react` for render and interaction tests
- Mock API calls via `src/test/mocks.ts` — never make real HTTP calls in component tests

### Common Patterns
- Data fetching: `const { data, isLoading } = useQuery({ queryKey: ['trades'], queryFn: fetchTrades, refetchInterval: POLL.NORMAL })`
- Admin gate: `<AdminOnly><DestructiveButton /></AdminOnly>`
- Loading state: `if (isLoading) return <Skeleton />`

## Dependencies

### Internal
- `../../api.ts` — REST API functions
- `../../polling.ts` — `POLL` interval constants
- `../../types.ts` — shared TypeScript interfaces
- `../../hooks/` — custom hooks for WebSocket, SSE, auth

### External
- `@tanstack/react-query` — data fetching and caching
- `recharts` — charts
- `framer-motion` — animations
- `lucide-react` — icons
