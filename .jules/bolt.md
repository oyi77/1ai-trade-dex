## 2024-05-30 - [Array .filter.length optimization]
**Learning:** High frequency re-renders in Dashboard table filters can trigger multiple unnecessary O(N) array passes (like chaining multiple `.filter(t => ...).length` inside render bodies).
**Action:** Consolidate multiple O(N) linear filter length checks into a single-pass `for` loop initialized and grouped inside a `useMemo` block.

## 2024-05-30 - [scipy and numpy conflict]
**Learning:** `pandas==3.0.3` requires `numpy>=1.26.0` (or `2.4.6`), but older versions of `scipy` (like `1.14.1`) strictly limit `numpy<2.3`. This creates a dependency resolution conflict in GitHub CI checks when installing backend requirements.
**Action:** When updating or maintaining `numpy` or `pandas` versions, ensure `scipy` is bumped to `1.15.2` (or a compatible version that allows `numpy>=2.3`) to prevent CI failure.
