<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# alembic

## Purpose
Root-level Alembic database migration configuration. Primary migrations are in `backend/alembic/`.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `versions/` | Migration version scripts (see `versions/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Prefer `backend/alembic/` for new migrations
- Root alembic is legacy; backend has the active migration chain
