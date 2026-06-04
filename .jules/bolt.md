## 2024-05-16 - Safe Spread Replacement Pattern (Correction)
**Learning:** When replacing `Math.max(0, ...array)` and `Math.min(0, ...array)` with `reduce`, always ensure to retain the explicitly passed `0` as the initial value of the reduce function if it was used in the original spread operation. The `0` acts as a chart axis anchor, and blindly swapping to `Infinity`/`-Infinity` introduces visual and functional regressions.
**Action:** When converting spread arrays to reduce, faithfully carry over any constant anchoring arguments to preserve exact chart scaling behaviors.
