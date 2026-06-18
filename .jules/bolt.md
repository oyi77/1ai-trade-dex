## 2024-05-30 - [Array .filter.length optimization]
**Learning:** High frequency re-renders in Dashboard table filters can trigger multiple unnecessary O(N) array passes (like chaining multiple `.filter(t => ...).length` inside render bodies).
**Action:** Consolidate multiple O(N) linear filter length checks into a single-pass `for` loop initialized and grouped inside a `useMemo` block.
