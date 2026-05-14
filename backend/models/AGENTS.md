# DATA MODELS & ORM
<!-- Parent: ../AGENTS.md -->

**Module**: `backend/models/` — SQLAlchemy ORM, database schema (2.1K LOC)

## PURPOSE

Central data layer: SQLAlchemy ORM definitions, database schema, migrations.

## KEY FILES

| File | LOC | Purpose |
|------|-----|---------|
| `database.py` | 2130 | SQLAlchemy ORM definitions, all models |

## CORE MODELS

| Model | Purpose | Key Fields |
|-------|---------|-----------|
| `StrategyConfig` | Strategy governance | id, name, enabled, win_rate, kill_date, ... |
| `Trade` | Live trades | id, strategy_id, market_id, size, pnl, settled_at, ... |
| `ShadowTrade` | Paper trading | id, strategy_id, outcome, fitness, ... |
| `StrategyGenome` | AGI genomes | id, genome_str, fitness, generation, promotion_date |
| `User` | Users | id, email, api_key, ... |
| `Market` | Market metadata | id, market_id, title, outcome_type, resolved_at |

## CRITICAL RULES

### StrategyConfig (Source of Truth)
- **enabled** field is authoritative; never bypass in code
- Auto-kill sets **enabled=False** + **kill_date=now()**
- Manual re-enable requires DB update (intentional friction)

### Trade Settlement
- **settled_at** timestamp marks settlement completion
- **pnl** calculated from outcome resolution
- No partial trades (atomic settlement)

### ShadowTrade (Fitness Feedback)
- Settled vs. real outcomes for fitness calculation
- Used to determine promotion/kill decisions
- Minimum trade sample required before auto-kill

## MIGRATIONS

Alembic (`alembic/versions/`) manages schema changes:

```bash
alembic upgrade head          # Apply all
alembic revision --autogenerate -m "msg"  # Create migration
alembic downgrade -1          # Revert one
```

Always include down() for rollback.

## ANTI-PATTERNS

- ❌ Direct SQL (use ORM)
- ❌ Missing down() in migrations
- ❌ Migrations that break backward compatibility
- ❌ Manual StrategyConfig updates without auditing

## TESTING

```bash
pytest backend/tests/ -k "model" -v
pytest backend/tests/test_database_*.py -v
```
