<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/alembic

## Purpose
Database migration framework using Alembic. Manages schema evolution for SQLite (Phase 1) and PostgreSQL (production).

## Key Files

| File | Description |
|------|-------------|
| `env.py` | Alembic environment configuration. Sets up SQLAlchemy engine and metadata for autogeneration. |
| `script.py.mako` | Migration script template. |
| `versions/20260421_comprehensive_schema_sync.py` | Comprehensive schema synchronization — adds tables, columns, and indexes for Phase 2 features. |
| `versions/20260421_error_logging.py` | Error logging schema — adds error log tables. |
| `versions/882388989397_add_settings_table.py` | Adds the `Settings` table for runtime configuration. |
| `versions/882388989398_phase2_feature_schemas.py` | Phase 2 feature schemas — adds new tables for AGI autonomy, experiments, and strategy health. |
| `versions/20260613_add_decision_execution_status.py` | Adds `decision_log.execution_status` + index (idempotent — re-applies a change a stray legacy migration already made on prod). |
| `versions/20260613_fix_ledger_wallet_sync_event_type.py` | Data fix: backfills 989 `transaction_events` rows with invalid `type='ledger_wallet_sync'` to `'reconciliation_adjustment'`. |

## For AI Agents

### Working In This Directory
- Always generate migrations with `alembic revision --autogenerate -m "description"`
- Test migrations on a fresh DB before applying to production
- Migrations must be idempotent and handle existing data gracefully
- **This is the ONLY directory for new migrations.** The root `alembic/`
  directory is legacy, has a *disconnected* revision graph, but points at
  the SAME `DATABASE_URL` (see `docs/alembic-dirs.md`). Running
  `alembic upgrade head` from the repo root once (commit `5c0a7801`) applied
  a stray migration to prod and set `alembic_version` to a revision ID
  (`arb_exec_status_001`) this directory's graph couldn't locate, breaking
  `alembic current`/`upgrade head` here entirely until fixed via
  `alembic stamp --purge add_arb_bundle_tracking` +
  `20260613_add_decision_execution_status.py`. The root `alembic/env.py` now
  raises immediately to prevent a repeat.

### Common Patterns
- Use `alembic upgrade head` to apply all pending migrations
- Use `alembic downgrade -1` to rollback the last migration
- Autogenerate detects SQLAlchemy model changes automatically

## Dependencies

### Internal
- `backend.models.database` — SQLAlchemy metadata for autogeneration

### External
- `alembic` — Migration framework
- `sqlalchemy` — ORM metadata

<!-- MANUAL: -->
