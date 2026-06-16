## 2025-02-23 - [Frontend Rendering Efficiency]
**Learning:** In real-time WebSockets powered dashboards, chaining high-order array methods like `.filter().length` or `.filter().reduce()` causes significant O(N) blocking times on the main UI thread during rapid state recalculations.
**Action:** Consolidate chained array iteration methods into single-pass `for` loops wrapped in `useMemo` hooks (or outside hooks if dependent on moving windows like `Date.now()`) to ensure consistent frame rates without re-calculation overhead.
