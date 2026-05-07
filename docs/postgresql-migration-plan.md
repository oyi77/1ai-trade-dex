# Polyedge PostgreSQL Migration Plan

## Why PostgreSQL

### The BotState Race Problem (T59)
- **86+ BotState mutation sites** across 39 files
- PM2 runs 3 processes (`api`, `worker`, `scheduler`) concurrently
- SQLite uses **database-level locking** — `SELECT ... FOR UPDATE` is a **no-op**
- Concurrent read-modify-write = **lost updates** on bankroll/pnl counters
- PostgreSQL uses **row-level locking** — `FOR UPDATE` actually locks the row

### PostgreSQL Benefits
- Row-level pessimistic locking (`SELECT ... FOR UPDATE`)
- True concurrent writes without corruption
- Better connection pooling (PgBouncer-ready)
- JSONB for semi-structured data (misc_data column)
- Full-text search for signal/market lookups
- Connection limits per service (no unlimited pool like SQLite)

---

## Architecture After Migration

```
Production (PM2):
┌─────────┐ ┌─────────┐ ┌─────────┐     ┌────────────┐
│  api    │ │ worker  │ │scheduler │ ──► │ PostgreSQL │
│ process │ │ process │ │ process  │     │   (host)   │
└─────────┘ └─────────┘ └─────────┘     └────────────┘

Development (single process):
┌─────────────┐     ┌────────────┐
│  uvicorn    │ ──► │  SQLite    │
│  (dev)      │     │ ./db.sqlite│
└─────────────┘     └────────────┘
```

---

## Implementation Tasks

### PHASE 1: PostgreSQL Engine & Config (Foundation)

**1.1** Update `backend/config.py`:
- Add `DATABASE_URL` pydantic validator with URL scheme validation
- Add `POSTGRES_POOL_SIZE` (default: 10)
- Add `POSTGRES_MAX_OVERFLOW` (default: 20)
- Add `POSTGRES_POOL_TIMEOUT` (default: 30)
- Add `POSTGRES_POOL_RECYCLE` (default: 3600)
- Add `POSTGRES_SSL_MODE` (default: "prefer")
- Detect dialect: `is_postgres = "postgresql" in DATABASE_URL`

**1.2** Update `backend/models/database.py`:
- Change engine creation to be dialect-aware:
  ```python
  _is_postgres = "postgresql" in settings.DATABASE_URL
  engine = create_engine(
      settings.DATABASE_URL,
      connect_args={"check_same_thread": False} if not _is_postgres else {},
      pool_size=settings.POSTGRES_POOL_SIZE if _is_postgres else 5,
      max_overflow=settings.POSTGRES_MAX_OVERFLOW if _is_postgres else 10,
      pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
      pool_recycle=settings.POSTGRES_POOL_RECYCLE,
      pool_pre_ping=True,
  )
  ```
- Add `SET TRANSACTION ISOLATION LEVEL READ COMMITTED` for PostgreSQL sessions
- Keep SQLite-specific WAL pragma conditional on `engine.dialect.name == "sqlite"`
- Add `FOR UPDATE` helper function:
  ```python
  def with_lock(session, query):
      """Add FOR UPDATE if PostgreSQL, pass through if SQLite."""
      dialect = session.get_bind().dialect.name
      if dialect == "postgresql":
          return query.with_for_update()
      return query  # SQLite: no-op
  ```

**1.3** Update `docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: polyedge
      POSTGRES_USER: ${POSTGRES_USER:-polyedge}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U polyedge"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  backend:
    environment:
      - DATABASE_URL=${DATABASE_URL:-postgresql+psycopg2://polyedge:changeme@postgres:5432/polyedge}
    depends_on:
      postgres:
        condition: service_healthy
```

**1.4** Update `.env.example`:
```
# Database
DATABASE_URL=sqlite:///./tradingbot.db
# For production with PostgreSQL (run docker-compose):
# DATABASE_URL=postgresql+psycopg2://polyedge:changeme@localhost:5432/polyedge

# PostgreSQL settings (used when DATABASE_URL starts with postgresql://)
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=20
POSTGRES_SSL_MODE=prefer
```

---

### PHASE 2: Fix BotState Race (T59 Core Fix)

**2.1** Create helper module `backend/core/db_locking.py`:
```python
"""Database dialect-aware locking utilities."""
from sqlalchemy.orm import Session

def for_update(session: Session, query):
    """Add FOR UPDATE clause if dialect supports it."""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return query.with_for_update()
    return query  # SQLite/MySQL: pass through
```

**2.2** Fix priority BotState sites with `for_update()`:

Files to update (`db.query(BotState).filter_by` → `for_update(db, db.query(BotState).filter_by)`):

| File | Line(s) | Context |
|------|---------|---------|
| `backend/core/strategy_executor.py` | ~144 | Primary bankroll read in trade execution path |
| `backend/core/settlement.py` | 565, 583, 601, 651 | Settlement reconciliation |
| `backend/core/bankroll_reconciliation.py` | ~491 | On-chain sync write |
| `backend/core/signals.py` | ~241 | Signal generation |
| `backend/core/scheduling_strategies.py` | 331, 469, 713 | Job-level state reads |
| `backend/api/system.py` | ~762 | Health/stats endpoints |
| `backend/core/orchestrator.py` | ~100 | Bot state init |

**2.3** Add atomic update helper for BotState:
```python
def atomic_botstate_update(db: Session, mode: str, updates: dict) -> BotState:
    """Atomically update BotState fields with row lock."""
    state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
    if not state:
        state = BotState(mode=mode)
        db.add(state)
    for key, value in updates.items():
        setattr(state, key, value)
    db.flush()
    return state
```

**2.4** Add test for concurrent BotState updates:
- Create `backend/tests/test_botstate_concurrency.py`
- Uses `threading` + multiple sessions to simulate concurrent read-modify-write
- Verify no lost updates with PostgreSQL
- Verify no crashes with SQLite (degraded but safe)

---

### PHASE 3: Data Migration (SQLite → PostgreSQL)

**3.1** Create `backend/db/migrate_to_postgres.py`:
```python
"""
SQLite to PostgreSQL migration script.
Run AFTER PostgreSQL schema is created via alembic.
Run BEFORE switching DATABASE_URL to PostgreSQL.

Usage:
  python -m backend.db.migrate_to_postgres --source sqlite:///./tradingbot.db \
                                           --dest postgresql+psycopg2://... \
                                           [--tables bot_state,trades,signals]
"""
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.models.database import Base

# Tables to migrate (in order of dependencies)
MIGRATION_ORDER = [
    "bot_state",
    "strategy_config",
    "signals",
    "trades",
    "decision_log",
    # ... add others
]

def migrate_table(source_engine, dest_engine, table: str, batch_size: int = 1000):
    """Migrate single table with batch inserts."""
    source_conn = source_engine.connect()
    dest_conn = dest_engine.connect()
    dest_conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))

    offset = 0
    while True:
        result = source_conn.execute(
            text(f"SELECT * FROM {table} LIMIT {batch_size} OFFSET {offset}")
        )
        rows = result.fetchall()
        if not rows:
            break

        columns = result.keys()
        for row in rows:
            placeholders = ", ".join([f":{c}" for c in columns])
            insert = text(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            )
            dest_conn.execute(insert, dict(zip(columns, row)))
        dest_conn.commit()
        offset += batch_size
        print(f"  {table}: migrated {offset} rows")

    source_conn.close()
    dest_conn.close()

def main():
    # Parse args, validate connections, run migrations in order
```

**3.2** Create Alembic migration for PostgreSQL schema:
```bash
# Generate migration from current SQLite schema
DATABASE_URL=sqlite:///./tradingbot.db alembic revision --autogenerate -m "pg_initial"

# Apply to PostgreSQL
DATABASE_URL=postgresql+psycopg2://... alembic upgrade head
```

**3.3** Update `alembic.ini` for multi-database:
```ini
[alembic:sqlite]
sqlalchemy.url = sqlite:///./tradingbot.db

[alembic:postgres]
sqlalchemy.url = postgresql+psycopg2://...

[alembic]
# Default to sqlite for dev
version_locations = alembic/versions
```

---

### PHASE 4: Dev Experience (SQLite Backwards Compat)

**4.1** Ensure SQLite users are not affected:
- Default `DATABASE_URL` still `sqlite:///./tradingbot.db`
- No PostgreSQL deps required for dev
- All existing migrations work with SQLite
- `docker-compose.yml` does NOT require postgres for dev

**4.2** Add `scripts/dev-start.sh`:
```bash
#!/bin/bash
# Start dev environment with SQLite
docker-compose up -d redis backend
```

**4.3** Add `scripts/prod-start.sh`:
```bash
#!/bin/bash
# Start production with PostgreSQL
docker-compose --profile prod up -d
```

---

### PHASE 5: Testing & Validation

**5.1** Local PostgreSQL test:
```bash
docker-compose up -d postgres
DATABASE_URL=postgresql+psycopg2://polyedge:changeme@localhost:5432/polyedge \
  python -c "from backend.models.database import engine; print(engine)"
# Should show: Engine(postgresql+psycopg2://...)

# Run migrations
alembic upgrade head

# Run tests
pytest backend/tests/test_botstate_concurrency.py -v
```

**5.2** SQLite regression test:
```bash
# Start without postgres
docker-compose up -d backend
# Should work with SQLite fallback

pytest backend/tests/ -v
```

**5.3** Validate `protect_live_bot_state_financial_fields` still works:
- Live mode financial fields (bankroll, total_pnl) protected
- PostgreSQL `FOR UPDATE` prevents concurrent overwrites
- SQLite falls back to existing protection logic

---

## File Change Summary

| File | Change Type | Lines |
|------|-------------|-------|
| `backend/config.py` | Modify | +30 |
| `backend/models/database.py` | Modify | +25 |
| `backend/core/db_locking.py` | Create | ~80 |
| `backend/core/strategy_executor.py` | Modify | +5 |
| `backend/core/settlement.py` | Modify | +8 |
| `backend/core/bankroll_reconciliation.py` | Modify | +5 |
| `backend/core/signals.py` | Modify | +3 |
| `backend/core/scheduling_strategies.py` | Modify | +8 |
| `backend/api/system.py` | Modify | +3 |
| `docker-compose.yml` | Modify | +25 |
| `.env.example` | Modify | +8 |
| `backend/db/migrate_to_postgres.py` | Create | ~200 |
| `backend/tests/test_botstate_concurrency.py` | Create | ~150 |
| `scripts/dev-start.sh` | Create | ~10 |
| `scripts/prod-start.sh` | Create | ~10 |
| `alembic.ini` | Modify | +15 |

**Total new code: ~550 lines**
**Total modified code: ~85 lines**

---

## Migration Path (Zero Data Loss)

```
Step 1: Deploy PostgreSQL (docker-compose up -d postgres)
Step 2: Generate PG schema (alembic revision --autogenerate)
Step 3: Run migration script (python -m backend.db.migrate_to_postgres)
Step 4: Verify row counts match
Step 5: Switch DATABASE_URL to postgresql://...
Step 6: Restart backend
Step 7: Rollback: switch back to sqlite://..., no data changed in SQLite
```

---

## Order of Execution

```
Phase 1 (can start immediately, no risk):
  1.1 → 1.2 → 1.3 → 1.4

Phase 2 (after Phase 1, core BotState fix):
  2.1 → 2.2 → 2.3 → 2.4

Phase 3 (after Phase 1, data migration):
  3.1 → 3.2 → 3.3

Phase 4 (after Phase 1, dev experience):
  4.1 → 4.2 → 4.3

Phase 5 (after all above, validation):
  5.1 → 5.2 → 5.3
```

Phase 1 and Phase 2 can run in parallel once Phase 1 is done.
Phase 3, 4, 5 are independent and can start after Phase 1.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| PostgreSQL connection fails | Fallback to SQLite if PG unavailable |
| Migration script data loss | TRUNCATE only after verified source row count |
| Existing alembic migrations break | Test on fresh PG db first |
| FOR UPDATE breaks SQLite | `for_update()` helper is no-op on SQLite |
| Pool size too small for PM2 | Configurable via env vars, PM2 can set larger |
| SSL mode issues | Default to "prefer" (not "require") |
