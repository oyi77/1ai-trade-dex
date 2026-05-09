<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# frontend

## Purpose
React 18 + TypeScript dashboard for monitoring and controlling the PolyEdge trading bot. Provides real-time trade feeds, strategy management, admin controls, AGI oversight, and market intelligence views. Built with Vite; deployed to Vercel.

## Key Files

| File | Description |
|------|-------------|
| `src/main.tsx` | App entry point — React root, query client setup |
| `src/App.tsx` | Root component — routing, auth gate, layout |
| `src/api.ts` | Axios client, WebSocket URL builder, all REST API calls |
| `src/api/agi.ts` | AGI-specific API calls |
| `src/types.ts` | Shared TypeScript interfaces for API response shapes |
| `src/types/features.ts` | Feature-specific type definitions |
| `src/polling.ts` | Polling interval constants (`POLL.FAST/NORMAL/SLOW/VERY_SLOW`) |
| `src/utils/auth.ts` | CSRF token and legacy API key helpers |
| `src/utils/retryFetch.ts` | Fetch wrapper with retry logic |
| `src/contexts/ModeFilterContext.tsx` | Trading mode filter context (paper/live/shadow) |
| `vite.config.ts` | Vite build configuration |
| `package.json` | Node dependencies and scripts |
| `playwright.config.ts` | E2E test configuration |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/components/` | Reusable UI components (see `src/components/AGENTS.md`) |
| `src/pages/` | Top-level page components — one per route |
| `src/hooks/` | Custom React hooks — data fetching, WebSocket, SSE |
| `src/test/` | Vitest unit tests and mocks |
| `e2e/` | Playwright end-to-end tests |

## For AI Agents

### Working In This Directory
- **Never append auth tokens to SSE/WS URLs** — realtime connections use cookie auth (`withCredentials: true`). The legacy `token=ADMIN_API_KEY` fallback is for backward compatibility only; new code must not rely on it.
- **Use `POLL.*` constants from `src/polling.ts`** for all polling intervals — never hardcode millisecond values.
- **API base URL is dynamic** — always use `API_BASE` from `src/api.ts`, never hardcode `localhost` or production URLs.
- All data fetching uses `@tanstack/react-query`; use `useQuery`/`useMutation` patterns, not raw `useEffect` + `fetch`.
- Feature flags from the backend are surfaced via the settings API — do not add frontend-only feature flags.

### Testing Requirements
- Unit tests: `cd frontend && npm test` (Vitest)
- E2E tests: `cd frontend && npx playwright test`
- Test files live in `src/test/` (unit) and `e2e/` (E2E)
- Mock API responses using `src/test/mocks.ts`

### Common Patterns
- Data fetching: `useQuery({ queryKey: ['key'], queryFn: apiFn, refetchInterval: POLL.NORMAL })`
- Mutations with cache invalidation: `useMutation({ mutationFn, onSuccess: () => queryClient.invalidateQueries(['key']) })`
- WebSocket connections: use `useWebSocket` hook from `src/hooks/useWebSocket.ts`
- SSE connections: use `useSSEEvents` hook from `src/hooks/useSSEEvents.ts`

## Dependencies

### External
- `react` 18 + `react-dom` — UI framework
- `@tanstack/react-query` — server state management
- `axios` — HTTP client
- `framer-motion` — animations
- `lucide-react` — icons
- `recharts` — charting
- `vite` — build tool
- `vitest` — unit test runner
- `@playwright/test` — E2E test runner
