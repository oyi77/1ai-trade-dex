<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# FRONTEND DASHBOARD

## Purpose
React 18 + TypeScript dashboard for trading bot monitoring, strategy control, and market intelligence. Real-time polling via configurable intervals. Vite build tool with Tailwind CSS styling.

## Key Files

| File | Description |
|------|-------------|
| `src/main.tsx` | App entry point — React root, query client setup |
| `src/App.tsx` | Root component — routing, auth gate, layout |
| `src/api.ts` | Axios client, WebSocket URL builder, all REST API calls |
| `src/api/agi.ts` | AGI-specific API calls |
| `src/api/data_sources.ts` | Data source management API |
| `src/api/market_venues.ts` | Market venue API client |
| `src/api/providers.ts` | Provider configuration API |
| `src/types.ts` | Shared TypeScript interfaces for API response shapes |
| `src/types/features.ts` | Feature-specific type definitions |
| `src/polling.ts` | Polling interval constants (`POLL.FAST/NORMAL/SLOW/VERY_SLOW`) |
| `src/utils/auth.ts` | CSRF token and legacy API key helpers |
| `src/utils/retryFetch.ts` | Fetch wrapper with retry logic |
| `src/contexts/ModeFilterContext.tsx` | Trading mode filter context (paper/live/shadow) |
| `vite.config.ts` | Vite build configuration |
| `package.json` | Node dependencies and scripts; `build:docs` skips gracefully when sibling `../polyedge-docs` checkout is absent |
| `playwright.config.ts` | E2E test configuration |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | Application source root (see `src/AGENTS.md`) |
| `src/components/` | 30+ React components (see `src/components/AGENTS.md`) |
| `src/components/dashboard/` | Dashboard tabs (see `src/components/dashboard/AGENTS.md`) |
| `src/components/admin/` | Admin panel tabs (see `src/components/admin/AGENTS.md`) |
| `src/components/hft/` | HFT UI components (see `src/components/hft/AGENTS.md`) |
| `src/components/__tests__/` | Co-located component tests (see `src/components/__tests__/AGENTS.md`) |
| `src/pages/` | Page-level components (see `src/pages/AGENTS.md`) |
| `src/hooks/` | Custom React hooks (see `src/hooks/AGENTS.md`) |
| `src/contexts/` | React contexts (see `src/contexts/AGENTS.md`) |
| `src/api/` | API client modules (see `src/api/AGENTS.md`) |
| `src/types/` | TypeScript type definitions (see `src/types/AGENTS.md`) |
| `src/utils/` | Utility functions (see `src/utils/AGENTS.md`) |
| `src/test/` | Vitest unit tests (see `src/test/AGENTS.md`) |
| `e2e/` | Playwright E2E tests (see `e2e/AGENTS.md`) |
| `public/` | Static assets — PWA manifest, icons, favicon (see `public/AGENTS.md`) |

## Key Modules

| File | Purpose |
|------|---------|
| `src/api.ts` | Fetch client, all API interactions |
| `src/pages/Landing.tsx` | Entry page, trading interface |
| `src/pages/LiveStream.tsx` | Real-time trade stream |
| `src/components/admin/SettingsTab.tsx` | Settings UI |
| `src/components/TradeNotifications.tsx` | Trade alerts |
| `src/pages/MiroFish.tsx` | MiroFish page |
| `src/components/admin/SettingsEditor.tsx` | Settings editor |
| `src/pages/WhaleTracker.tsx` | Whale tracking UI |
| `src/components/dashboard/OverviewTab.tsx` | Dashboard overview |
| `src/types.ts` | TypeScript types |

## Polling Configuration

Configurable intervals (see `polling.ts`):

```typescript
VITE_POLL_FAST_MS       // Fast polling (real-time trades)
VITE_POLL_NORMAL_MS     // Normal polling (strategy updates)
VITE_POLL_SLOW_MS       // Slow polling (market data)
VITE_POLL_VERY_SLOW_MS  // Very slow polling (analytics)
```

## For AI Agents

### Working In This Directory
- Components use React hooks (no class components)
- State management: React Context (see `contexts/`)
- Async API calls: use `api.ts` fetch client
- Tests: Vitest for unit tests, Playwright for E2E
- TypeScript: strict mode required
- Styling: Tailwind CSS dark/noir theme

### Testing Requirements
```bash
npm run test       # Vitest unit tests
npm run e2e        # Playwright E2E tests
npm run lint       # ESLint
```

### Common Patterns
- Lazy routes in App.tsx use React.lazy() + Suspense
- Admin operations require Bearer token auth via `adminApi` interceptor
- Real-time updates via WebSocket subscriber in useWebSocket hook
- Tables use DataTable component with useTableQuery for sorting/filtering

### Anti-Patterns
- Direct fetch calls outside `api.ts`
- Long-lived polling intervals (respect server load)
- Silent API errors (error logging required)
- Non-memoized expensive components

## Dependencies

### External
- `react@18`, `react-router-dom@7` — routing and navigation
- `axios@1` — REST client
- `tailwindcss@3` — utility CSS framework
- `typescript@5` — type safety
- `vite@5` — build tool
- `vitest@4`, `@testing-library/react` — unit testing
- `@playwright/test@1` — E2E testing
- `@tanstack/react-query@5` — server state management
- `framer-motion@10` — animations
- `recharts@2` — charts
- `lucide-react` — icons
