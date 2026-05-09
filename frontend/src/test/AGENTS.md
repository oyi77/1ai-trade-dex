<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# test

## Purpose
Vitest unit and component tests using React Testing Library. Covers API client utilities, custom hooks (useTableQuery, useWebSocket, useAuth), key page components (PendingApprovals, TradingTerminal), and shared components (DataTable, LiveMarketView, OpportunityScanner, WhaleActivityFeed). setup.ts configures jest-dom matchers. mocks.ts provides shared mock data and MSW (Mock Service Worker) mocks for API and axios.

## Key Files
| File | Type | Description |
|------|------|-------------|
| setup.ts | config | Imports @testing-library/jest-dom to extend vitest with DOM matchers (toBeInTheDocument, toHaveTextContent, etc.). Configures test environment. |
| mocks.ts | utilities | Provides vi.mock() for api module and axios. Mock functions return Promise.resolve() with typical response shapes. Used by all tests. |
| api.test.ts | unit | Tests API client functions: fetch endpoints, error handling, retry logic, query parameter serialization. |
| useTableQuery.test.ts | unit | Tests pagination, sorting, filtering, and caching logic of custom hook. |
| useWebSocket.test.ts | unit | Tests WebSocket connection lifecycle: connect, disconnect, reconnect, message handling, subscriptions. |
| DataTable.test.tsx | component | Tests table rendering, pagination controls, sorting headers, row selection, column visibility. |
| LiveMarketView.test.tsx | component | Tests market data display, price updates, bid/ask spread visualization. |
| OpportunityScanner.test.tsx | component | Tests opportunity detection, filtering, ranking, and real-time updates. |
| WhaleActivityFeed.test.tsx | component | Tests whale transaction feed, transaction details, sorting, filtering by whale address. |
| PendingApprovals.test.tsx | component | Tests approval list rendering, batch operations (approve/reject/clear all), trade details modal. |
| TradingTerminal.test.tsx | component | Tests layout composition, component integration (LiveMarketView, OpportunityScanner, WhaleActivityFeed). |
| Landing.i18n.test.tsx | component | Tests internationalization (i18n) for landing page components and localization strings. |
| Settings.mirofish.test.tsx | component | Tests MiroFish integration in settings components and debate system functionality. |
| WinningTradesPreview.test.tsx | component | Tests winning trades preview component and performance visualization features. |
| retryFetch.test.ts | unit | Tests retry logic for failed network requests and exponential backoff implementation. |
| ControlRoomTab.test.tsx | component | Tests control room tab functionality and system monitoring interface. |
| ModeFilter.test.tsx | component | Tests mode filtering functionality and system state management. |

## For AI Agents

### Working In This Directory
- Tests use Vitest as the test runner (configured in vite.config.ts, package.json scripts: `test` and `test:watch`).
- React Testing Library provides render(), screen, userEvent, fireEvent utilities.
- All tests import setup.ts automatically (configured in vitest.config or tsconfig).
- Mocks are applied at module level in mocks.ts and imported by individual test files (or auto-mocked).
- Tests avoid implementation details; focus on user-visible behavior (screen.getByRole, screen.getByText).
- Async operations use waitFor() for assertions after state updates or async handlers.
- WebSocket and API mocks resolve/reject promises to simulate success/error states.

### Testing Requirements
- All page components and hooks must have corresponding test files in this directory.
- Mock api module (mocks.ts) provides consistent mock functions across all tests.
- Mock axios with interceptors for authentication headers and error handling.
- DataTable and form components: test user interactions (click, type, submit).
- Real-time components (LiveMarketView, WhaleActivityFeed): mock WebSocket subscriptions with vitest.mock().
- useAuth hook: test authenticated and unauthenticated code paths separately.
- useTableQuery hook: test pagination state, sort direction changes, filter application.
- useWebSocket hook: test connection, subscription, message handling, and reconnection.
- Coverage target: >80% for utils, >75% for components.

### Common Patterns
- **Setup in beforeEach**: Call vi.clearAllMocks() to reset mock call counts between tests.
- **Component Rendering**: render(<Component />, { wrapper: QueryClientProvider or custom wrapper if needed }).
- **Async Assertions**: Use await waitFor(() => expect(...).toBe(...)) for state updates and async effects.
- **Mock Data**: Import realistic data shapes from mocks.ts (trades, whale_transactions, opportunities, etc.).
- **User Interactions**: userEvent.click(), userEvent.type() for form inputs; fireEvent for events mock doesn't handle.
- **Query Client**: Each test gets a fresh QueryClient instance (or reset in beforeEach) to avoid state leakage.
- **Mock Verification**: Assert vi.fn().toHaveBeenCalledWith(...) to verify correct API calls and props passed to children.
- **Error Paths**: Test API errors (404, 500), network failures, and timeout scenarios.

## Dependencies

### Internal
- `../api/` - Mock in mocks.ts (getAdminApiKey, setAdminApiKey, fetchDashboard, fetchDecisions, decisionsExportUrl, etc.)
- `../hooks/` - Tested directly (useAuth, useTableQuery, useWebSocket, useStats)
- `../components/` - Tested as child components (DataTable, LiveMarketView, OpportunityScanner, PendingApprovals, TradingTerminal, etc.)
- `../pages/` - Key pages tested here (PendingApprovals.tsx, TradingTerminal.tsx)
- mocks.ts - Shared mock data and vitest mocks

### External
- vitest (^4.1.2) - Test runner
- @testing-library/react (^16.3.2) - render, screen, waitFor, userEvent
- @testing-library/jest-dom (^6.9.1) - DOM matchers (toBeInTheDocument, toHaveClass, etc.)
- @testing-library/user-event (^14.6.1) - User interaction simulation
- jsdom (^29.0.2) - DOM environment for vitest
- @tanstack/react-query (^5.17.9) - useQuery, useMutation (mocked in tests)
- react-router-dom (^7.14.0) - Link, Routes (mocked in component tests as needed)
- axios (^1.6.5) - Mocked in mocks.ts
- @vitest/ui (^4.1.2) - Optional: visual test runner interface

<!-- MANUAL: -->
