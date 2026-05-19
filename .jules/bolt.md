## 2023-10-27 - [N+1 Query Bottleneck in Knowledge Graph Operations]
**Learning:** The `KnowledgeGraph` class in `backend/core/knowledge_graph.py` contains N+1 query patterns in multiple methods (e.g. `get_related`, `find_pattern`, `get_strategies_for_regime`) where it iterates over `relations` and performs a database `.first()` query for each relation's associated entity. This is an architecture-specific performance anti-pattern.
**Action:** When working with SQLAlchemy queries that iterate over multiple relations to fetch associated entities, always use the `in_` operator to bulk-fetch the entities in a single query and perform an O(1) dictionary lookup within the loop.

## 2024-05-10 - [React Re-renders on WebSocket Data Updates]
**Learning:** In dashboards powered by fast-polling or WebSocket streams (e.g. `useStats` hook triggering rapid component updates), derived array calculations like `.filter()`, `.map()`, and especially `.sort()` within the render body can block the UI thread and consume heavy CPU if unmemoized. This codebase frequently renders long lists of trade arrays that should not be re-calculated unless the specific array reference or filters change.
**Action:** When updating dashboard tabs and data grids handling lists of trades or streams, wrap expensive array transformations and aggregations in `useMemo` so that rapid state updates from independent contexts (like stats or health ticks) don't force redundant iterations over unchanged data.

## 2024-05-24 - [Avoid lockfile changes when optimizing]
**Learning:** In a heavily configured frontend setup using pnpm and Vite, running `npm run` or installing dependencies indiscriminately just to get linting/tests working can severely pollute lockfiles and break cross-platform builds by unlinking platform specific packages like `esbuild`.
**Action:** When making minor React performance optimizations, do NOT touch package.json or install new versions of build tools (like Vite) just to fix testing environments. Restore any untracked lockfile modifications before creating a PR to ensure safe, localized optimization.

## 2026-05-19 - [Memoizing derived UI tab configurations in React]
**Learning:** In the React frontend, UI configuration arrays that depend on expensive operations like `.filter()` over large lists (e.g. mapping over trade lists to compute tab counts) will execute O(M*N) operations on *every render* if placed directly in the component body. This was observed in `TradesTable.tsx` where filter tab counts were recalculated on every render, severely impacting performance for long lists.
**Action:** Always wrap UI configuration arrays that compute lengths or derived state from props using `useMemo` to ensure O(N) operations only occur when the underlying data changes, rather than on every component render.
