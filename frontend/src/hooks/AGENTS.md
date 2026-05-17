<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# frontend/src/hooks

## Purpose
Custom React hooks encapsulating shared business logic: authentication state management, real-time WebSocket connection handling with automatic reconnection, dashboard stats polling, server-side paginated table data fetching with sorting/filtering, real-time trade event streaming, Server-Sent Events, brain graph visualization, and MiroFish integration.

## Key Files

| File | Description |
|------|-------------|
| `useAuth.ts` | Authentication state hook — manages admin API key in localStorage, provides login/logout functions, checks if auth is required, returns isAuthenticated flag and authRequired state |
| `useWebSocket.ts` | WebSocket connection hook — connects to URL, handles message parsing, auto-reconnects with exponential backoff (retries up to 5 times), provides status (connecting/open/closed/error) and sendMessage function |
| `useStats.ts` | Dashboard stats polling hook — fetches bot statistics (total return, Sharpe, win rate, max drawdown, etc.) on configurable interval, uses React Query for caching |
| `useTableQuery.ts` | Paginated table data hook — fetches server-side paginated data with sorting (column, direction) and filtering, returns page of results, total count, and handlers for sort/filter/page changes |
| `useTradeEvents.ts` | Real-time trade events hook — subscribes to WebSocket stream of trade notifications, returns list of recent trade events and subscription status |
| `useSSEEvents.ts` | Server-Sent Events hook — handles real-time data streams via SSE protocol with automatic reconnection and event parsing |
| `useBrainGraph.ts` | Brain graph visualization hook — manages knowledge graph rendering and node relationships |
| `useMiroFish.ts` | MiroFish integration hook — manages external dual-debate system communication |
| `useActivity.ts` | Activity tracking hook — logs and displays system activities and user interactions |
| `useProposals.ts` | Trade proposal hook — manages AI-generated trade proposals and review workflow |
| `useModeFilter.ts` | Filter mode hook — delegates to ModeFilterContext for paper/testnet/live filtering |
| `useSSEEvents.test.tsx` | Unit tests for the SSE events hook — connection lifecycle, message parsing, error recovery |

## For AI Agents

### Working In This Directory
- Each hook is a self-contained logic unit with a single responsibility
- Hooks manage their own state with `useState()` and fetch state with `useQuery()`
- WebSocket hooks use `useRef()` for mutable state (connection, retry count) to avoid triggering re-renders
- useAuth checks API key from localStorage and validates via `/api/admin/auth-required` endpoint
- useStats polls with `refetchInterval` from polling.ts constants
- useTableQuery accepts `page`, `pageSize`, `sort`, `filter` parameters and returns data + handlers
- All fetch URLs constructed with `import.meta.env.VITE_API_URL` fallback to empty string
- Error handling: catch and set error state, UI can read hook status to show error message

### Testing Requirements
- useAuth tests: verify login/logout persist to localStorage, verify auth check endpoint call, verify isAuthenticated computed correctly
- useWebSocket tests: mock WebSocket constructor, simulate connect/message/disconnect, verify reconnection logic, verify sendMessage calls ws.send()
- useStats tests: mock useQuery call, verify fetch URL, verify refetch interval set, test error handling
- useTableQuery tests: verify fetch parameters (page, sort, filter), verify handler functions update state, test pagination boundaries
- useSSEEvents tests: mock EventSource, verify connection lifecycle, message parsing, error recovery
- All tests use `renderHook()` from @testing-library/react
- Disable automatic reconnection in WebSocket tests by setting `closedByUser.current = true`

### Common Patterns
- useAuth: single source of truth for admin API key, called by protected routes to validate access
- useWebSocket: provides generic T interface for type-safe message parsing, caller parses JSON
- useStats: caches stats to avoid excessive polling, invalidate cache on demand for fresh data
- useTableQuery: server-side pagination only — no client-side filtering, sort/filter done by backend
- useSSEEvents: long-lived subscription with automatic reconnection on connection loss
- useTradeEvents: long-lived subscription — component unmount doesn't close connection, handle cleanup with useEffect return
- All hooks check `enabled` flag before fetching (e.g., skip fetch if not authenticated)

## Dependencies

### Internal
- `../api.ts` — api client instance, adminApi client, fetch function calls
- `../types.ts` — type definitions for BotStats, Trade, Signal, etc.
- `../contexts/ModeFilterContext.tsx` — mode filter state (used by useModeFilter)
- `../polling.ts` — polling interval constants

### External
- `react@18` — useState, useEffect, useRef, useCallback
- `@tanstack/react-query@5` — useQuery, useQueryClient for server state management
