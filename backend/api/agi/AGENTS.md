<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# agi

## Purpose
AGI-specific API endpoints. Provides the Knowledge Graph query interface for strategy evolution, gene performance, and market relationship exploration.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `kg_router.py` | FastAPI router for Knowledge Graph operations — `/api/agi/knowledge-graph/query` endpoint |

## Subdirectories

None.

## For AI Agents

### Working In This Directory
- Router is mounted in the main FastAPI app under `/api/agi/knowledge-graph`
- Uses `KnowledgeGraph` from `backend.application.agi.knowledge_graph`
- Returns JSON graph data for strategy evolution visualization

### Testing Requirements
- Run: `pytest backend/tests/test_api_health.py -v`

### Common Patterns
- Standard FastAPI router with `Depends(get_db)` for session injection
- Returns structured JSON for frontend graph visualization

## Dependencies

### Internal
- `backend.application.agi.knowledge_graph` — KnowledgeGraph operations
- `backend.models.database` — Database session

### External
- `fastapi` — API framework
- `sqlalchemy` — ORM

<!-- MANUAL: -->