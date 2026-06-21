## 2024-06-09 - [Fixing call stack limits in React]
**Learning:** Math.max and Math.min with spread operators on potentially large mapped array (e.g. `Math.max(...arr.map(x => x.val))`) will cause `Maximum call stack size exceeded` in JS engines like V8.
**Action:** Use `.reduce()` such as `arr.reduce((max, x) => Math.max(max, x.val), -Infinity)` instead to avoid creating temporary mapped arrays and hitting call stack limits. Avoid creating redundant arrays inside `reduce` as well.
