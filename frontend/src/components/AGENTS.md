# REACT COMPONENTS
<!-- Parent: ../AGENTS.md -->

**Module**: `frontend/src/components/` — 30+ React components (UI logic)

## PURPOSE

Reusable React components for dashboard: tabs, cards, charts, forms, admin tools.

## COMPONENT CATEGORIES

### Dashboard Tabs

- `dashboard/OverviewTab.tsx` (423 LOC) — Portfolio overview
- `dashboard/MarketIntelTab.tsx` (390 LOC) — Market signals
- `dashboard/WhaleTrackerTab.tsx` (403 LOC) — Whale tracking

### Admin Tools

- `admin/SettingsTab.tsx` (543 LOC) — Settings UI
- `admin/SettingsEditor.tsx` (451 LOC) — Settings editor
- `admin/AITab.tsx` (375 LOC) — AI controls

### Notifications & Alerts

- `TradeNotifications.tsx` (531 LOC) — Trade alerts
- `ProposalApprovalUI.tsx` (494 LOC) — Approval workflows

### Shared Components

- `ErrorBoundary.tsx` (367 LOC, test file) — Error boundary wrapper

## CONVENTIONS

- Props: TypeScript interfaces required
- State: useContext + useState; avoid Redux
- Effects: useEffect with dependency arrays (ESLint enforced)
- API calls: use `api.ts` fetch client, never direct fetch
- Memoization: useMemo for expensive computations

## ANTI-PATTERNS

- ❌ Direct fetch calls (use api.ts)
- ❌ Props drilling deep (use Context)
- ❌ useEffect without dependencies
- ❌ Non-memoized expensive renders

## TESTING

```bash
npm run test -- components/
npm run e2e -- components/
```
