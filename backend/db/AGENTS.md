<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/db

## Purpose

Database utilities and connection management for the trading bot. Provides session management with automatic commit/rollback handling, retry logic for database locks, and transaction lifecycle management.

## Key Files

| File | Description |
|------|-------------|
| `utils.py` | Database session manager with automatic commit/rollback and retry logic for database locks |

## For AI Agents

### Working In This Directory
- Database connections use SQLAlchemy session management
- All database operations should use the session context manager
- Automatic retry logic handles database contention issues

### Testing Requirements
- Test sessions should use in-memory SQLite for isolation
- Verify transaction rollback behavior on exceptions
- Test lock retry mechanism under concurrent access

### Common Patterns
- Use `with get_db_session() as db:` for all database operations
- Session automatically commits on successful exit, rolls back on exceptions
- Retry logic handles SQLite lock contention with exponential backoff
- Always close sessions in finally blocks to prevent connection leaks

## Dependencies

### Internal
- `backend.models.database` — SQLAlchemy session factory and ORM models

### External
- `sqlalchemy` — ORM and session management
- `contextlib` — Context manager utilities