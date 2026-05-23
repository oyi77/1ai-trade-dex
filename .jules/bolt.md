## 2024-05-18 - N+1 Query in `backend/core/knowledge_graph.py` (`_query_best_genes_volatile_regime`)
**Learning:** Found N+1 query loops inside the graph queries in `backend/core/knowledge_graph.py`, like `_query_best_genes_volatile_regime` and `_query_highest_alpha_by_category`. The loop iterates over a list of queried strategy nodes and issues a DB query on each iteration. We can batch this using `in_` operator in SQLAlchemy.
**Action:** Replace the loop over nodes with a single `in_` query to fetch all edges/related nodes.
