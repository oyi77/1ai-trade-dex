# Alembic Directory Structure (G-35)

## Canonical Directory: `backend/alembic/`

The **active** Alembic migration directory is `backend/alembic/`. This is where new migrations should be created.

## Root `alembic/` Directory

The root `alembic/` directory contains **legacy migrations** from before the backend was restructured into a package. These migrations are preserved for historical reference but should NOT be used for new migrations.

**Do not create new migrations in `alembic/versions/`.** Always use `backend/alembic/versions/`.

**Do not run `alembic` from the repo root at all.** Its `env.py` now raises
immediately on import. Both `alembic.ini` files point `env.py` at the same
`settings.DATABASE_URL`, but the two `versions/` directories are
*disconnected* revision graphs sharing one `alembic_version` row. On
2026-06-11, running `alembic upgrade head` from the root (after adding a
migration to the legacy dir, commit `5c0a7801`) applied that migration to
prod and left `alembic_version='arb_exec_status_001'` — a revision ID
`backend/alembic`'s graph doesn't have, breaking `alembic current`/
`upgrade head` there. Fixed 2026-06-13 via `alembic stamp --purge
add_arb_bundle_tracking` + `backend/alembic/versions/
20260613_add_decision_execution_status.py` (re-applies the stray column
idempotently) + `20260613_fix_ledger_wallet_sync_event_type.py` (data
backfill for a downstream `TransactionEvent.type` corruption this caused).

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
