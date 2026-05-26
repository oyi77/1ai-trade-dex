## 2024-05-26 - [React Array Recalculations]
**Learning:** Found an anti-pattern where a statically sized array containing multiple `.filter()` aggregations was defined directly in the render body of a large table component (`TradesTable`), causing `4 * O(N)` recalculations on every sort/filter state change and blocking the UI thread.
**Action:** Always verify if complex array derivations (like building filter option summaries) are properly wrapped in `useMemo` and scoped to their actual dependencies (e.g. `[trades]`).
