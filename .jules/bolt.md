
## 2024-06-19 - [O(N) Render Blocking in Equity Chart via Map/Spread]
**Learning:** Using `Math.max(...data.map(...))` inside React components on potentially large arrays like `EquityChart` data forces the main UI thread to do multiple full passes (O(N)) and risks a stack overflow when the dataset grows too large because of the spread operator expanding array elements into function arguments.
**Action:** When calculating min/max over arrays of unknown size, replace map+spread chains with a single-pass `for` loop wrapped in a `useMemo` hook, or use a `.reduce()` function to maintain performance and avoid `Maximum call stack size exceeded` errors.
