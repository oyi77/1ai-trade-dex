<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# frontend/src/api

## Purpose
API client modules providing typed HTTP wrappers for backend endpoints. Each module focuses on a specific domain: AGI system, data sources, market venues, and provider configuration. All modules share the `adminApi` Axios instance from `src/api.ts` for authenticated requests.

## Key Files

| File | Description |
|------|-------------|
| `agi.ts` | AGI API client — `fetchProposals()`, `fetchExperiments()`, `fetchGenomes()`, `createProposal()`, `approveProposal()`, `rejectProposal()`. Manages AI strategy proposals and approval workflows. |
| `data_sources.ts` | Data source management — configure and monitor external data feeds (market data, news, sentiment). CRUD operations for data source connections. |
| `market_venues.ts` | Market venue API — manage trading venue connections (Polymarket, Kalshi). Venue status, market listings, order routing configuration. |
| `providers.ts` | Provider configuration — manage LLM/AI provider settings (Groq, Claude, OmniRoute). Provider health checks, API key management, model selection. |

## For AI Agents

### Working In This Directory
- All functions use `adminApi` from `../api.ts` for authenticated requests
- Return typed promises: `Promise<Proposal[]>`, `Promise<Experiment[]>`, etc.
- Handle errors with `.catch()` and return empty arrays on failure
- Each module is independently importable — no cross-dependencies between api/ files

### Common Patterns
- Import `adminApi` from `../api.ts` (not direct Axios)
- Use `async/await` with try/catch for error handling
- Cache results with React Query at the call site, not in the API layer
- Return empty arrays/objects on error to prevent UI crashes

## Dependencies

### Internal
- `../api.ts` — Axios instances (`api` for public, `adminApi` for authenticated)
- `../types.ts` — TypeScript interfaces for request/response shapes

### External
- `axios` — HTTP client
