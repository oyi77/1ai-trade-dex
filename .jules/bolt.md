## 2024-05-31 - [Math.max maximum call stack size]
**Learning:** Using `Math.max(...array)` with a spread operator on potentially unbounded data arrays (like Leaderboard filtered traders) can crash the UI thread with a "Maximum call stack size exceeded" error.
**Action:** Use an iterative approach (`for` loop with manual max tracking) for finding max values in unpaginated or large dataset arrays instead of spreading into `Math.max`.
