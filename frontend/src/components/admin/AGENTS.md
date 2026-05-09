<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# frontend/src/components/admin

## Purpose
Admin panel tab components. Each tab provides a distinct control surface for system configuration: AI model settings, API credential management, wallet setup, risk limit configuration, settings JSON editor, strategy on/off and parameter tuning, system health monitoring, Telegram bot integration, copy trading setup, and market watchlist management.

## Key Files

| File | Description |
|------|-------------|
| `AITab.tsx` | AI model provider config — select Groq/Claude/OmniRoute/custom, set API keys/URLs, manage daily token budget, track usage, test suggestions, and apply AI-generated signals |
| `CredentialsTab.tsx` | API credential management — Polymarket CLOB key/secret, Kalshi API key, and other market data provider authentication |
| `WalletConfigTab.tsx` | Wallet setup and configuration — connect wallets, set trade sizing rules, manage deposit/withdrawal addresses |
| `RiskTab.tsx` | Risk limit controls — max position size, max portfolio drawdown, daily loss limit, circuit breaker thresholds, strategy-specific risk caps |
| `SettingsEditor.tsx` | JSON settings editor — raw JSON view of all bot settings, edit and save with validation feedback |
| `StrategiesTab.tsx` | Strategy control panel — enable/disable individual strategies, run strategies manually, monitor required credentials and error states |
| `SystemStatus.tsx` | System health dashboard — bot status, connection health, queue length, error log tail, uptime metrics |
| `TelegramTab.tsx` | Telegram bot integration — set bot token, configure notification rules, manage allowed users, test message send |
| `CopyTraderMonitor.tsx` | Copy trading monitoring — track copied trades, performance vs leader, auto-execution status, position reconciliation |
| `MarketWatchTab.tsx` | Market watchlist — add/remove tracked markets, set alert thresholds, monitor key metrics (volume, spread, price changes) |
| `DebateMonitorTab.tsx` | MiroFish debate monitoring — track external dual-debate validation, decision confidence, fallback engine status |
| `AGIRegimeTab.tsx` | AGI regime control — manage autonomy levels, safety boundaries, and decision authority |
| `AGIDecisionsTab.tsx` | AGI decisions log — review AI-generated decisions, reasoning, and approval workflow |
| `AGIControlTab.tsx` | AGI system control — enable/disable autonomous functions, override decisions, manual intervention |
| `AGIComposerTab.tsx` | AGI strategy composer — configure strategy evolution, crossover, mutation parameters |
| `SettingsTab.tsx` | General settings tab — global configuration options, feature flags, system preferences |

## Subdirectories
None — all admin components are at root level of `admin/`.

## For AI Agents

### Working In This Directory
- Each tab is self-contained and independently fetchable via React Query
- Admin API calls require Bearer token auth — passed automatically by `adminApi` interceptor
- Use `useQueryClient()` to invalidate related queries after mutations (e.g., after updating strategy, refetch strategies)
- Form state managed with local `useState()` — validate before submit
- Loading states while fetching/saving: show spinners or disable buttons
- Error messages displayed in status message boxes: `{ ok: false, message: '...' }`
- Credentials tab handles sensitive data — show masked inputs for keys/secrets
- Strategy tab polls for strategy list every 30s (refetchInterval)
- All numeric inputs validated before sending to API

### Testing Requirements
- Mock all admin API calls via `adminApi` using fixtures
- Test that mutations trigger correct query invalidations
- Test form validation (empty fields, invalid formats)
- Test loading/error states in each tab
- Test that sensitive data (API keys) is masked in UI
- Test credential error handling (invalid key rejected)
- Avoid testing localStorage directly — test via useAuth hook

### Common Patterns
- Fetch data on component mount with `useQuery()`
- Track mutation state with local `useState()` (loading, status)
- Collect form inputs in state, validate on submit
- Call `adminApi.post()` or `adminApi.patch()` for mutations
- Invalidate related queries after successful mutations
- Display success/error toast via `setStatus({ ok: boolean, message: string })`
- Guard sensitive operations with confirmation dialogs

## Dependencies

### Internal
- `../../api.ts` — adminApi client, fetchStrategies, updateStrategy, fetchAdminSettings, updateAdminSettings, fetchAISuggest, etc.
- `../../types.ts` — type definitions for settings, strategies, AI status
- `../../hooks/useAuth.ts` — authentication validation

### External
- `react@18` — useState, useQuery, useQueryClient, etc.
- `@tanstack/react-query@5` — useQuery for data fetching and caching
- `tailwindcss@3` — styling and layout

<!-- MANUAL: -->
