<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# docs/architecture

## Purpose
Architecture Decision Records (ADRs) and structural documentation for system design. Documents major technical decisions (job queue backend, API modularization), trade-offs, consequences, and the reasoning behind them. Provides context for how and why the system is organized.

## Key Files

| File | Description |
|------|-------------|
| `adr-001-job-queue.md` | Decision to use SQLite-first job queue (Phase 1) with optional Redis upgrade (Phase 2) — explains why APScheduler was insufficient, how idempotency is enforced, migration path to Redis |
| `adr-002-live-equity-source.md` | Decision that live BotState equity is derived from CLOB USDC cash + Polymarket open-position value, not local realized P&L/backfill ledger rows |
| `adr-003-trade-attempt-observability.md` | Decision to add a durable TradeAttempt ledger and Control Room UI for explaining executed and rejected trade attempts |
| `adr-004-bounded-autonomous-sizing.md` | Decision to let AI/strategy logic propose dynamic sizes only inside deterministic risk mandates |
| `adr-005-static-risk-profiles-and-learning-boundary.md` | Decision for static risk profile presets (safe, normal, aggressive, extreme) with learning boundaries for AGI strategy evolution |
| `adr-006-agi-autonomy-framework.md` | Decision for bounded AGI autonomy with promotion gates, safety boundaries, and human-in-the-loop override for experiment lifecycle |
| `API_STRUCTURE.md` | FastAPI modularization — documents router separation (auth, markets, trading, phase2, system, ws_manager), core infrastructure (EventBus, error handling), migration from monolithic 3188-line main.py to modular design |

## Decision Record Format

Each ADR follows the pattern:
- **Status** — Accepted, Superseded, or Deprecated
- **Date** — Decision timestamp
- **Context** — Problem drivers and constraints
- **Decision** — What was chosen and why
- **Alternatives Considered** — Options evaluated and rejected
- **Consequences** — Positive and negative outcomes

## For AI Agents

### Working In This Directory
- ADRs are immutable once accepted — new decisions get new ADR numbers (adr-002.md, adr-003.md, etc.)
- When making architectural decisions, create an ADR before implementation
- Document the business/operational constraint that motivated the choice (e.g., "zero new infra", "tight job deadlines")
- Explain why simpler alternatives were rejected (not just what they are)
- Link ADRs from code comments when implementation depends on the decision

### Common Patterns
- Architecture decisions driven by operational constraints (single-VPS target, job durability, offline development)
- Phase 1 / Phase 2 patterns allow shipping with minimal infrastructure, upgrading later
- Interface-based design (AbstractQueue) isolates backends — Phase 2 is a configuration change, not a code rewrite
- Trade-offs explicitly stated — e.g., "SQLite WAL has write concurrency limits vs. Redis" is a known consequence, not a hidden gotcha

### Adding New Records
1. Determine the next ADR number
2. Copy template: status, date, deciders, context, decision, alternatives, consequences
3. Link from API_STRUCTURE.md or other docs as appropriate
4. Discuss with team before "Accepted" — this is decision documentation, not implementation log

## Dependencies

### Internal
- `backend/core/queue/` — AbstractQueue interface and SQLiteQueue implementation follow adr-001
- `backend/api/` — Router structure follows API_STRUCTURE.md modularization
- `ARCHITECTURE.md` — High-level system overview (complements these detailed records)

### External
- None — this is reference documentation, no external dependencies

<!-- MANUAL: -->
