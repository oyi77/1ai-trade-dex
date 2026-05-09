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

## For AI Agents

### Working In This Directory
- Always generate migrations with `alembic revision --autogenerate -m "description"`
- Test migrations on a fresh DB before applying to production
- Migrations must be idempotent and handle existing data gracefully

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
