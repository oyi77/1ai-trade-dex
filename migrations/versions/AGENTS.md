<!-- Parent: ../AGENTS.md -->
<!-- Updated: 2026-05-27 -->

# migrations/versions

## Purpose
Database migration version scripts (secondary migration directory). Contains a single initial schema migration. The primary migration directory is `backend/alembic/versions/` which contains all subsequent migrations.

## Key Files

| File | Description |
|------|-------------|
| `46ed961e0cde_initial_schema.py` | Initial database schema migration |

## For AI Agents

### Working In This Directory
- This is a legacy/secondary migration directory with only the initial schema
- **All active migrations live in `backend/alembic/versions/`** — do not create new migrations here
- Run with `alembic upgrade head` from the project root
- Never modify a migration that has been applied to production

## Dependencies

### Internal
- `backend/db/` — SQLAlchemy model definitions

### External
- `alembic` — Migration framework
- `sqlalchemy` — ORM
