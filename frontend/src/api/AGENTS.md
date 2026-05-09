<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# frontend/src/api

## Purpose
AGI-specific API client functions. Provides typed HTTP wrappers for backend AGI endpoints.

## Key Files

| File | Description |
|------|-------------|
| `agi.ts` | AGI API client functions: `fetchProposals()`, `fetchExperiments()`, `fetchGenomes()`, `createProposal()`, `approveProposal()`, `rejectProposal()`. Uses the same Axios instance as `src/api.ts` with Bearer token auth. |

## For AI Agents

### Working In This Directory
- All functions use `adminApi` from `src/api.ts` for authenticated requests
- Return typed promises: `Promise<Proposal[]>`, `Promise<Experiment[]>`, etc.
- Handle errors with `.catch()` and return empty arrays on failure

### Common Patterns
- Import `adminApi` from `../api.ts` (not direct Axios)
- Use `async/await` with try/catch for error handling
- Cache results with React Query at the call site, not in the API layer

## Dependencies

### Internal
- `src/api.ts` — Axios instances (public and admin)
- `src/types.ts` — TypeScript interfaces

### External
- `axios` — HTTP client

<!-- MANUAL: -->
