<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-10 -->

# pages

## Purpose
Top-level page components mapped to React Router routes. Each page is a full-screen view representing a major feature area. Landing.tsx is the public investor-focused marketing/entry page with right-aligned Dashboard, Docs, and Research navigation. Dashboard.tsx hosts the main tabbed monitoring interface. Admin.tsx provides system administration and strategy configuration. TradingTerminal.tsx displays live market data and trading opportunities. Other pages handle backtest results, market intelligence, trade approvals, settlement tracking, whale activity monitoring, strategy edge tracking, and decision logging.

## Key Files
| File | Route | Description |
|------|-------|-------------|
| Landing.tsx | / | Cinematic Investment Dossier landing page with live research ticker, right-aligned Dashboard/Docs/Research navigation, EN/ID/RU/CH language selector with IP/browser defaulting, AGI Trading Systems hero, problem→breakthrough→mechanism→proof→allocation story, decision-flow audit ledger, research paper assets, and configurable allocation CTA via VITE_LANDING_* env vars. |
| Dashboard.tsx | /dashboard | Main hub with 7-tab interface: Overview, Trades, Signals, Markets, Leaderboard, Decisions, Performance. Uses React Query for data fetching and socket subscriptions for real-time updates. |
| Admin.tsx | /admin | System administration panel with password-gated access. Tabs for Strategies, Market Watch, Wallet Config, Credentials, Telegram, Risk Settings, AI Config. Embeds Backtest component and PendingApprovals. |
| TradingTerminal.tsx | /trading-terminal | Live trading interface combining LiveMarketView, OpportunityScanner, and WhaleActivityFeed in a 2-column layout. |
| Backtest.tsx | (embedded in Admin) | Runs and displays strategy backtests with result visualization. |
| PendingApprovals.tsx | /pending-approvals | Lists pending trades requiring human confirmation. Supports batch approve/reject/clear operations. |
| WhaleTracker.tsx | /whale-tracker | Monitors large wallet movements and their correlation with market movements. Uses DataTable with pagination and sorting. |
| Settlements.tsx | /settlements | Tracks trade settlements and reconciliation status. |
| MarketIntel.tsx | /market-intel | Market intelligence dashboard with trends, sentiment, and opportunity analysis. |
| DecisionLog.tsx | /decisions | Historical decision log with filtering and export. Uses useTableQuery hook for pagination and sorting. |
| EdgeTracker.tsx | /edge-tracker | Tracks strategy edge metrics and performance statistics. |

## For AI Agents

### Working In This Directory
- All pages are functional React components (not class components).
- Pages are lazy-loaded in App.tsx (except Landing, Dashboard, Admin which are eager).
- Each page handles its own authentication via `useAuth()` hook or component-level guards.
- Pages use `useQuery` and `useMutation` from @tanstack/react-query for server state.
- Real-time updates via WebSocket are managed through custom hooks (e.g., `useWebSocket`).
- Pages are wrapped in `Suspense` boundaries in App.tsx except for the three eager-loaded pages.
- Styling uses Tailwind CSS with a dark/noir theme (black, grays, and accent colors).
- Framer Motion provides animations and transitions.

### Testing Requirements
- Page components tested in `src/test/` using Vitest + React Testing Library.
- Mock API responses in `mocks.ts` for all pages that depend on server data.
- Mock useAuth hook to test authenticated vs unauthenticated states.
- Mock useQuery to test loading/error/success states.
- Mock WebSocket subscriptions for real-time data pages.
- Dashboard tabs each have focused test coverage (see test files).

### Common Patterns
- **Landing CTA**: `Landing.tsx` primary and secondary CTA labels/URLs are configurable via `VITE_LANDING_CTA_LABEL`, `VITE_LANDING_CTA_URL`, `VITE_LANDING_SECONDARY_CTA_LABEL`, and `VITE_LANDING_SECONDARY_CTA_URL` in `frontend/.env.example`. The landing page uses verified static proof stats only; do not add live-performance claims unless backed by a verified source.
- **Landing Language**: `Landing.tsx` supports `en`, `id`, `ru`, and `ch` copy directly in the page. Default selection order is saved `localStorage` choice (`polyedge.landing.language`) → IP country lookup via `https://api.country.is/` → browser language → English. Keep `src/test/Landing.i18n.test.tsx` in sync when changing language behavior.
- **Authentication Gate**: useAuth() hook. If !isAuthenticated, show LoginModal.
- **Async Data Loading**: useQuery for fetching, useMutation for mutations. Refetch on tab change or manual triggers.
- **Real-Time Updates**: useWebSocket hook subscribes to channels (e.g., 'trades', 'whale_activity'). Auto-reconnect on disconnect.
- **Tab Navigation**: Dashboard and Admin use state-managed tab switching with tab components (OverviewTab, TradesTab, etc.).
- **Export/Download**: Some pages (DecisionLog) provide CSV/JSON export via API endpoint construction.
- **Modal/Dialog**: LoginModal and SettingsEditor used for user input; managed with local state.
- **Error Boundaries**: App.tsx ErrorBoundary catches runtime errors; pages handle API errors gracefully.

## Dependencies

### Internal
- `../hooks/` - useAuth, useStats, useTableQuery, useWebSocket
- `../api/` - fetchDashboard, runScan, simulateTrade, startBot, stopBot, getAdminApiKey, setAdminApiKey, fetchDecisions, decisionsExportUrl
- `../components/` - StatsCards, LoginModal, dashboard tabs, admin subcomponents, table/chart components
- App.tsx - Router and route definitions

### External
- react-router-dom (route navigation, Link, Navigate)
- @tanstack/react-query (useQuery, useMutation, useQueryClient)
- framer-motion (motion, AnimatePresence for animations)
- axios (HTTP client, configured in api.ts)
- recharts (charts and visualizations)
- lucide-react (icons)
- react-leaflet, leaflet, react-map-gl, mapbox-gl (map components for MarketIntel, WhaleTracker)
- three, react-globe.gl (3D globe visualization)
- date-fns (date formatting)
- tailwindcss (styling)

<!-- MANUAL: -->
