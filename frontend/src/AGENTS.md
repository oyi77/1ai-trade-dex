<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-10 -->

# frontend/src

## Purpose
React application source root. Defines the main application structure with React Router for navigation, REST/WebSocket API clients, shared TypeScript interfaces, service worker for offline support, and component hierarchy for monitoring and trading dashboard.

## Key Files

| File | Description |
|------|-------------|
| `App.tsx` | Root component — error boundary, React Router setup, lazy-loaded page routes (Dashboard, Admin, WhaleTracker, Settlements, MarketIntel, DecisionLog, TradingTerminal, PendingApprovals, EdgeTracker) |
| `api.ts` | REST client setup — `api` (public endpoints), `adminApi` (JWT-authenticated via localStorage), helper functions for dashboard, signals, trades, BTC prices, windows, wallets |
| `types.ts` | Shared TypeScript interfaces — `BtcPrice`, `Microstructure`, `BtcWindow`, `Signal`, `Trade`, `DashboardData`, `BotStats`, `WeatherForecast`, `WeatherSignal` |
| `main.tsx` | Vite entry point — React 18 StrictMode, app root mount, guarded service-worker registration |
| `sw.ts` | Service worker registration for offline support and caching |
| `index.css` | Global Tailwind CSS styles and custom utility classes |
| `utils.ts` | Shared utilities (formatting, time conversion, calculations) |
| `vite-env.d.ts` | Vite type definitions |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `components/` | Reusable React components — UI building blocks (NavBar, SignalsTable, TradesTable, DataTable, charts, modals, tabs for Admin and Dashboard) |
| `pages/` | Page-level components — full screens (Landing, Dashboard, Admin, WhaleTracker, Settlements, MarketIntel, DecisionLog, TradingTerminal, PendingApprovals, EdgeTracker, Backtest) |
| `hooks/` | Custom React hooks — `useAuth`, `useWebSocket`, `useStats`, `useTradeEvents`, `useTableQuery` |
| `test/` | Test setup and test files — `setup.ts`, `mocks.ts`, component and hook unit tests, API mocks (see `test/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- All components are TypeScript React with Tailwind CSS for styling
- API calls use axios instances from `api.ts` — never import axios directly
- Admin operations require `Authorization: Bearer {token}` header injected by `adminApi` interceptor
- Types must be imported from `types.ts` — keep types.ts as the single source of truth
- Lazy routes in App.tsx use React.lazy() + Suspense; add new pages here before creating the file
- Service worker managed by `sw.ts` — handles offline caching and push notifications.

### Testing Requirements
- Component tests in `test/` use Vitest + React Testing Library
- Mock API calls in test files using fixtures from `test/mocks.ts`
- Test data should reflect real API shapes (use `types.ts` shapes)
- WebSocket tests use mock event emitter pattern
- E2E tests in `frontend/e2e/` cover full user workflows (Playwright); unit tests focus on component logic

### Common Patterns
- All async data loading uses custom hooks (useStats, useTableQuery, useWebSocket)
- Admin UI guarded by `useAuth()` hook and API key validation
- Real-time updates via WebSocket subscriber in useWebSocket hook
- Tables use DataTable component with useTableQuery for sorting/filtering
- Error states display via TradeNotifications component
- Toast notifications use TradeNotifications (trade alerts) and error boundary fallback

## Dependencies

### Internal
- Backend API: `GET /api/dashboard`, `/api/signals`, `/api/trades`, `/api/wallets`, `/api/admin/*` endpoints
- Backend WebSocket: market data and event streams
- `e2e/` — Playwright specs for routing and dashboard rendering
- `hooks/` — useAuth, useWebSocket, useStats, useTableQuery
- `components/` — 30+ reusable UI components

### External
- `react@18`, `react-router-dom@7` — routing and navigation
- `axios@1` — REST client
- `tailwindcss@3` — utility CSS framework
- `typescript@5` — type safety
- `vite@5` — build tool
- `vitest`, `@testing-library/react` — unit testing
- `@playwright/test` — E2E testing (in `e2e/`)

<!-- MANUAL: -->
