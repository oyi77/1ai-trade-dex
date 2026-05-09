<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/models

## Purpose
SQLAlchemy ORM models, session factory, and database connection management. All persistent data structures are defined here. Schema changes require an Alembic migration.

## Key Files

| File | Description |
|------|-------------|
| `database.py` | All ORM models, `Base`, `get_db`, `SessionLocal`, `botstate_mutex`, `for_update` — the central schema file |
| `app_state.py` | In-memory application state (non-persisted runtime state) |
| `audit_logger.py` | `AuditLog` write helpers |
| `backtest.py` | Backtest-specific model helpers |
| `genome_registry.py` | `GenomeRegistry`, `GenomePerformance`, `GenomeShadowTrade` ORM models for genome persistence |
| `hft_tables.py` | HFT execution record model helpers |
| `historical_data.py` | Historical market data model helpers |
| `kg_models.py` | Knowledge graph node/edge model helpers |
| `outcome_tables.py` | Outcome tracking model helpers |

## ORM Models in `database.py`

| Model | Purpose |
|---|---|
| `Trade` | Executed trades — paper and live |
| `Signal` | Strategy-generated signals (pre-execution) |
| `BotState` | Singleton bot state — bankroll, PnL, mode |
| `StrategyConfig` | Per-strategy enabled/disabled flag and params |
| `Experiment` | AGI experiment lifecycle records |
| `TradeAttempt` | Durable ledger of all execution attempts (executed + rejected) |
| `PendingApproval` | Trades awaiting manual approval |
| `SettlementEvent` | Market settlement records |
| `TransactionEvent` | Deposit/withdrawal/settlement ledger |
| `StrategyProposal` | AI-generated strategy improvement proposals |
| `MiroFishSignal` | MiroFish debate system signals |
| `ActivityLog` | Strategy activity log |
| `AuditLog` | Admin action audit trail |
| `DecisionLog` | AI decision records |
| `PerformanceMetric` | Per-strategy performance snapshots |
| `EvolutionLog` | Genome evolution event log |
| `GenomeRegistry` | Genome persistence (also in `genome_registry.py`) |
| `Alert` / `AlertConfig` | Alert instances and configuration |
| `Setting` / `SystemSettings` | Runtime settings |
| `WalletConfig` | Wallet configuration |
| `BtcPriceSnapshot` | BTC price history |
| `EquitySnapshot` | Equity curve snapshots |
| `CalibrationRecord` | Probability calibration records |
| `KgNode` / `KgEdge` | Knowledge graph nodes and edges |
| `ErrorLog` | Structured error records |
| `ClobEvent` | CLOB order book events |

## For AI Agents

### Working In This Directory
- **Schema changes require an Alembic migration** — run `alembic revision --autogenerate -m "description"` then `alembic upgrade head`. Never modify existing migration files.
- **`botstate_mutex` must be imported and used for all BotState read-modify-write operations** — it is defined in `database.py` and exported for use in `core/`. See `backend/core/AGENTS.md` for the pattern.
- **`BotState` is a singleton** — there is exactly one row. Always query with `.first()` and guard against `None`.
- **`for_update()` is a helper for `SELECT FOR UPDATE`** — use it when acquiring a row lock inside a mutex-protected block.
- **`Trade` rows are append-only** — never mutate historical trade records to explain rejected attempts. Use `TradeAttempt` instead (ADR-003).
- `StrategyConfig.enabled` is the authoritative enabled/disabled flag — the AGI health check writes to this column; do not bypass it.

### Adding a New Model
1. Add the class to `database.py` inheriting from `Base`
2. Run `alembic revision --autogenerate -m "add_my_model"` from project root
3. Review the generated migration in `alembic/versions/`
4. Run `alembic upgrade head`
5. Add the model to the table above

### Testing Requirements
- Always use in-memory SQLite: `create_engine("sqlite:///:memory:", ...)`
- Call `Base.metadata.create_all(engine)` in test setup
- Never test against the production DB file

## Dependencies

### Internal
- `backend.config` — `settings` for DB URL and connection params

### External
- `sqlalchemy` — ORM, session management, column types
- `alembic` — schema migrations
