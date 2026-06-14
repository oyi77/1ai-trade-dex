## 2024-05-24 - [Avoid O(N) recalculation blocks in real-time Dashboards]
**Learning:** Multiple array filter operations chained or defined in rapid succession (like `.filter(t => t.result === 'win').length`) inside a React component's main body block the UI thread during frequent updates or with large event lists.
**Action:** Use a single-pass iterative `for` loop wrapped in a `useMemo` hook to calculate multiple conditions simultaneously to avoid blocking recalculations and prevent dropping frames during state changes.
