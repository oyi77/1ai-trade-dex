# Alembic Directory Structure (G-35)

## Canonical Directory: `backend/alembic/`

The **active** Alembic migration directory is `backend/alembic/`. This is where new migrations should be created.

## Root `alembic/` Directory

The root `alembic/` directory contains **legacy migrations** from before the backend was restructured into a package. These migrations are preserved for historical reference but should NOT be used for new migrations.

**Do not create new migrations in `alembic/versions/`.** Always use `backend/alembic/versions/`.

## Configuration

- `alembic.ini` (root) — Points to `backend/alembic/env.py` as the migration env
- `backend/alembic/env.py` — SQLAlchemy model metadata import and migration context

## Creating New Migrations

```bash
cd backend
alembic revision --autogenerate -m "description of change"
alembic upgrade head
```

## References

- `backend/alembic/AGENTS.md` — Agent guidance for migrations
- `backend/models/database.py` — SQLAlchemy model definitions (source of truth for schema)
