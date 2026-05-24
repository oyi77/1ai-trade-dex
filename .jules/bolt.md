## 2024-05-24 - Bulk query for shadow validation
**Learning:** Replaced O(N) database queries with a bulk query in `shadow_validation_job` when fetching shadow trades for multiple candidate genomes. A dictionary group-by pattern provides O(1) lookups inside the evaluation loop while keeping time sorting intact.
**Action:** When iterating over a collection and querying relations (e.g., candidate genomes -> shadow trades), use SQLAlchemy `in_` operators and map results in-memory instead of executing a query per item.
