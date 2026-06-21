## 2025-02-26 - O(N) Array Spread Risks in Frontend Charts
**Learning:** Using `Math.max(...array.map(...))` on large time-series chart datasets creates two severe performance bottlenecks:
1. It risks "Maximum call stack size exceeded" exceptions on very large datasets because each array item is passed as a separate argument to the stack.
2. It causes multiple `O(N)` loop executions and memory-hogging intermediate array allocations.
**Action:** Always replace spread syntax for min/max array bounds on time-series charts with a single O(N) iterative `for` loop wrapped in a `useMemo`. Ensure edge case boundaries (e.g. `0` or `-Infinity`) are properly initialized in the loop setup.
