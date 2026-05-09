<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# frontend/src/utils

## Purpose
Utility functions shared across the frontend. Provides auth helpers and retry logic for API calls.

## Key Files

| File | Description |
|------|-------------|
| `auth.ts` | Authentication utilities: `getAdminKey()`, `setAdminKey(key)`, `clearAdminKey()`. Reads/writes `localStorage.adminApiKey`. Validates key format (hex string, 32+ chars). |
| `retryFetch.ts` | Retry logic for fetch requests: exponential backoff with jitter. Used by `src/api.ts` for resilient API calls. Exports `retryFetch(url, options, maxRetries, baseDelay)`. |

## For AI Agents

### Working In This Directory
- Auth utilities are synchronous — no async operations
- Retry logic is generic and works with any `fetch`-like function
- All utilities are pure functions with no side effects (except `localStorage` in `auth.ts`)

### Common Patterns
- `getAdminKey()` returns `null` if not set or invalid
- `retryFetch` throws after exhausting retries; caller handles the error

## Dependencies

### External
- `typescript` — Type safety

<!-- MANUAL: -->
