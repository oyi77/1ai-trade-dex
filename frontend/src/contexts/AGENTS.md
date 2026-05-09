<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# frontend/src/contexts

## Purpose
React contexts for global state management. Provides mode filter context for dashboard views.

## Key Files

| File | Description |
|------|-------------|
| `ModeFilterContext.tsx` | React context for strategy mode filtering (paper, testnet, live). Provides `ModeFilterProvider` and `useModeFilter()` hook. |

## For AI Agents

### Working In This Directory
- Contexts are used sparingly — prefer React Query for server state
- All contexts wrap the app in `src/App.tsx`
- Use `useContext(MyContext)` in components, not direct imports

### Common Patterns
- Context providers are placed in `src/App.tsx` near the root
- Default values prevent null errors during testing

## Dependencies

### External
- `react` — Context API

<!-- MANUAL: -->
