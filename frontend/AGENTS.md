# FRONTEND DASHBOARD
<!-- Parent: ../AGENTS.md -->

**Module**: `frontend/` — React 18 + TypeScript dashboard (23K LOC)

## PURPOSE

React dashboard for trading bot monitoring, strategy control, market intelligence. Real-time polling via configurable intervals. Vite build tool.

## STRUCTURE

```
frontend/src/
├── components/      # 30+ React components
│   ├── dashboard/   # Dashboard tabs (Overview, Markets, Whales)
│   ├── admin/       # Settings, AITab, SettingsEditor
│   └── ...
├── pages/           # Page containers (Landing, LiveStream, MiroFish, etc.)
├── hooks/           # Custom React hooks
├── test/            # Vitest unit tests
├── e2e/             # Playwright E2E tests
├── api.ts           # Fetch client (1076 LOC, all API interactions)
├── types.ts         # TypeScript types (350 LOC)
├── polling.ts       # Configurable polling intervals
├── App.tsx          # Root component
├── main.tsx         # Vite entry point
├── index.css        # Global styles
└── contexts/, utils/  # Helpers
```

## KEY MODULES

| File | LOC | Purpose |
|------|-----|---------|
| `api.ts` | 1076 | Fetch client, all API interactions |
| `pages/Landing.tsx` | 680 | Entry page, trading interface |
| `pages/LiveStream.tsx` | 604 | Real-time trade stream |
| `components/admin/SettingsTab.tsx` | 543 | Settings UI |
| `components/TradeNotifications.tsx` | 531 | Trade alerts |
| `pages/MiroFish.tsx` | 484 | MiroFish page |
| `components/admin/SettingsEditor.tsx` | 451 | Settings editor |
| `pages/WhaleTracker.tsx` | 410 | Whale tracking UI |
| `components/dashboard/OverviewTab.tsx` | 423 | Dashboard overview |
| `types.ts` | 350 | TypeScript types |

## POLLING CONFIGURATION

Configurable intervals (see `polling.ts`):

```typescript
VITE_POLL_FAST_MS       // Fast polling (real-time trades)
VITE_POLL_NORMAL_MS     // Normal polling (strategy updates)
VITE_POLL_SLOW_MS       // Slow polling (market data)
VITE_POLL_VERY_SLOW_MS  // Very slow polling (analytics)
```

## BUILD & DEPLOY

```bash
npm run dev        # Vite dev server
npm run build      # Production build
npm run test       # Vitest unit tests
npm run e2e        # Playwright E2E tests
```

Build output: `frontend/dist/`

## CONVENTIONS

- Components use React hooks (no class components)
- State management: React Context (see `contexts/`)
- Async API calls: use `api.ts` fetch client
- Tests: Vitest for unit tests, Playwright for E2E
- TypeScript: strict mode required

## ANTI-PATTERNS

- ❌ Direct fetch calls outside `api.ts`
- ❌ Long-lived polling intervals (respect server load)
- ❌ Silent API errors (error logging required)
- ❌ Non-memoized expensive components

## TESTING

```bash
npm run test                     # Vitest
npm run e2e                      # Playwright
pytest frontend/e2e/            # If Python-based E2E exists
```
