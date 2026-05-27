<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# frontend/src/components/__tests__

## Purpose
Co-located component tests for complex components that benefit from having tests alongside the component source rather than in the shared `src/test/` directory. Currently contains the ErrorBoundary component test which validates error catching, fallback rendering, and recovery behavior.

## Key Files

| File | Description |
|------|-------------|
| `ErrorBoundary.test.tsx` | ErrorBoundary component tests — verifies catch of render errors, lifecycle errors, and fetch errors; tests fallback UI rendering, retry/reset functionality, and error recovery flows |

## For AI Agents

### Working In This Directory
- Tests use Vitest + React Testing Library (same setup as the shared test directory)
- This directory is for tests tightly coupled to a specific component — prefer the shared test directory for most tests
- The `ErrorBoundary.test.tsx` mocks `console.error` to suppress expected error output during testing
- Tests cover both synchronous render throws and asynchronous lifecycle errors

### Testing Requirements
- Run with: `npx vitest run src/components/__tests__/` from the frontend/ directory
- Uses `@testing-library/react` render and screen utilities
- Uses `@testing-library/jest-dom` matchers (configured in the shared test setup file)
- Mock `console.error` in beforeEach/afterEach to avoid noisy test output

### Common Patterns
- `ThrowingComponent` pattern: component that conditionally throws based on props
- `LifecycleThrowingComponent` pattern: class component that throws in `componentDidMount`
- `window.fetch` mocking for async error scenarios
- `fireEvent.click()` to trigger retry/reset actions
- `waitFor()` for async assertion after state updates

## Dependencies

### Internal
- `../ErrorBoundary.tsx` — the component under test
- `../../test/setup.ts` — Vitest setup with jest-dom matchers (relative path)

### External
- `vitest` — test runner
- `@testing-library/react` — render, screen, fireEvent, waitFor
- `@testing-library/jest-dom` — DOM matchers
- `react` — React.Component for class-based test components
