<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# migrations/versions

## Purpose
Database migration version scripts (secondary migration directory). Contains timestamped and named migration files for schema evolution. The primary migration directory is `backend/alembic/versions/`.

## Key Files

| File | Description |
|------|-------------|
| `51c2bc15c671_initial_schema.py` | Initial schema migration (largest, 17KB) |
| `20260315_task2_add_outcome_tables.py` | Outcome/trade result tables |
| `20260421_*.py` | Data validation constraints and comprehensive schema sync |
| `20260504_*.py` | Genome registry, shadow trade, evolution log, knowledge graph tables |
| `20260507_*.py` | Trade role column, CLOB events table |
| `20260514_add_signal_log_table.py` | Signal logging table |
| `20260517_*.py` | DB integrity constraints, trade token columns, provider credentials |
| `*_merge_*.py` | Alembic merge migrations resolving parallel branches |

## For AI Agents

### Working In This Directory
- Migrations follow a naming convention: `YYYYMMDD_description.py` or `<hash>_description.py`
- Run with `alembic upgrade head` from the project root
- Never modify a migration that has been applied to production
- Merge migrations (`merge_*.py`) are auto-generated to resolve branching -- do not create manually
- Ensure both `upgrade()` and `downgrade()` are implemented and reversible

## Dependencies

### Internal
- `backend/db/` -- SQLAlchemy model definitions

### External
- `alembic` -- Migration framework
- `sqlalchemy` -- ORM
