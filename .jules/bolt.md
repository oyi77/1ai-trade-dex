## 2026-06-20 - N+1 Query Batching with Strict Timestamp Boundaries
**Learning:** When attempting to resolve an N+1 query issue for historical trade logs (`DecisionLog`), fetching records between the global `min(timestamp)` and `max(timestamp)` of the entire paginated batch can cause massive OOM issues if the batch spans days or years.
**Action:** Always batch related time-series queries using exact match conditions (`or_` statements combining ticker, strategy, and tight per-trade timebounds) rather than loosely fetching a global time range for the whole batch.
