## 2025-06-15 - React Frontend O(N) Array Operations Refactoring
**Learning:** Chained array higher-order functions like `.filter().length` in React components executing inside `useMemo` on every derived array calculation block the main thread and add unnecessary rendering overhead, especially when parsing large trade history sets (10k+ items).
**Action:** Consolidate chained higher-order functions into a single-pass `for` loop iteration with `useMemo` caching to significantly reduce calculation time from O(K * N) to O(N).
