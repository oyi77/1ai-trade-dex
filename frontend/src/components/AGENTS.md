<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# frontend/src/components

## Purpose
Reusable React components for the trading dashboard. Includes UI building blocks (NavBar, DataTable, charts), feature-specific components (TradeNotifications, OpportunityScanner), and organized subdirectories for dashboard tabs, admin panels, and HFT components.

## Key Files

| File | Description |
|------|-------------|
| `ErrorBoundary.tsx` | Error boundary wrapper — catches runtime errors, renders fallback UI with retry option |
| `NavBar.tsx` | Top navigation bar — route links, auth status, mode selector |
| `DataTable.tsx` | Generic table component — pagination, sorting, column visibility, row selection |
| `TradesTable.tsx` | Trade display table — formatted P&L, direction indicators, timestamps |
| `SignalsTable.tsx` | Signal display — edge, confidence, probability columns with color coding |
| `StatsCards.tsx` | Dashboard stat cards — total return, Sharpe, win rate, drawdown |
| `TradeNotifications.tsx` | Trade alert system — real-time notifications, toast messages, alert history |
| `OpportunityScanner.tsx` | Opportunity detection — market scanning, ranking, filtering |
| `WhaleActivityFeed.tsx` | Whale transaction feed — large wallet movements, market impact |
| `LiveMarketView.tsx` | Live market data — real-time prices, bid/ask spreads, volume |
| `LoginModal.tsx` | Authentication modal — API key input, login flow |
| `FilterBar.tsx` | Data filtering controls — date range, market, strategy filters |
| `ActivityTimeline.tsx` | Event timeline — chronological system activity display |
| `ProposalApprovalUI.tsx` | Trade proposal approval — review, approve/reject workflow |
| `ProposalApprovalPanel.tsx` | Approval panel container — batch operations, queue management |
| `PageLoader.tsx` | Loading spinner — full-page loading state |
| `Skeleton.tsx` | Skeleton loader — content placeholder during data fetch |
| `BrainGraph.tsx` | Knowledge graph visualization — node relationships, interactive exploration |
| `AGIGraphRunner.tsx` | AGI graph execution — strategy evolution visualization |
| `GlobeView.tsx` | 3D globe — geographic market visualization using react-globe.gl |
| `EdgeDistribution.tsx` | Edge distribution chart — strategy edge histogram |
| `CalibrationPanel.tsx` | Model calibration — probability calibration controls |
| `MicrostructurePanel.tsx` | Market microstructure — order book depth, spread analysis |
| `PluginStatusPanel.tsx` | Plugin status — active plugins, health indicators |
| `VenueMonitor.tsx` | Venue monitoring — trading venue status, latency |
| `SandboxMonitor.tsx` | Sandbox environment — test environment status |
| `WeatherPanel.tsx` | Weather signals — weather-based trading signal display |
| `AdminOnly.tsx` | Auth guard — renders children only for authenticated admin users |
| `Terminal.tsx` | CLI terminal — command-line interface for bot control |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `dashboard/` | Dashboard tab components (see `dashboard/AGENTS.md`) |
| `admin/` | Admin panel tab components (see `admin/AGENTS.md`) |
| `hft/` | HFT UI components (see `hft/AGENTS.md`) |
| `__tests__/` | Co-located component tests (see `__tests__/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Props: TypeScript interfaces required for all component props
- State: useContext + useState; avoid Redux
- Effects: useEffect with dependency arrays (ESLint enforced)
- API calls: use `api.ts` fetch client, never direct fetch
- Memoization: useMemo for expensive computations, React.memo for pure components
- Styling: Tailwind CSS with dark/noir theme (black, grays, accent colors)

### Testing Requirements
```bash
npm run test -- src/components/
npx vitest run src/components/__tests__/
```

### Common Patterns
- Error boundary wraps page-level components in App.tsx
- DataTable used for all tabular data with useTableQuery hook
- Modals managed with local useState (open/close)
- Loading states via Skeleton or PageLoader components
- Conditional rendering with AdminOnly guard

### Anti-Patterns
- Direct fetch calls (use api.ts)
- Props drilling deep (use Context)
- useEffect without dependencies
- Non-memoized expensive renders

## Dependencies

### Internal
- `../api.ts` — REST API client
- `../types.ts` — TypeScript interfaces
- `../hooks/` — Custom hooks (useAuth, useTableQuery, useWebSocket)
- `../contexts/` — React contexts (ModeFilterContext)

### External
- `react@18` — Core React
- `@tanstack/react-query@5` — Server state
- `framer-motion@10` — Animations
- `recharts@2` — Charts
- `lucide-react` — Icons
- `tailwindcss@3` — Styling
- `reactflow@11` — Node-based graph visualization
- `three@0.182`, `react-globe.gl` — 3D globe
- `react-leaflet`, `react-map-gl` — Map components
