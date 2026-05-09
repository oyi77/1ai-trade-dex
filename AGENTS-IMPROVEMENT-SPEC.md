# AGENTS.md Improvement Spec

**Audited:** 2026-05-09  
**Scope:** Root `AGENTS.md` + all subdirectory `AGENTS.md` files  
**Files audited:** 9 AGENTS.md files across the repo

---

## Summary

The root `AGENTS.md` is well-structured and contains accurate, actionable guidance. The problem is coverage: the root references 6 subdirectory AGENTS.md files that don't exist, 8 leaf-level AGENTS.md files have broken parent links, and the most critical directory in the codebase (`backend/core/`, 115 files) has no documentation at any level. The strategy governance section also contains stale and contradictory data.

---

## Issues

### P0 — Broken reference chain (blocks agent navigation)

The root AGENTS.md references these files in its Subdirectories table. None exist:

| Referenced file | Status |
|---|---|
| `backend/AGENTS.md` | Missing |
| `frontend/AGENTS.md` | Missing |
| `docs/AGENTS.md` | Missing |
| `tests/AGENTS.md` | Missing |
| `scripts/AGENTS.md` | Missing |
| `backend/modules/AGENTS.md` | Missing |

Additionally, 8 existing leaf AGENTS.md files declare `<!-- Parent: X -->` where X does not exist:

| Leaf file | Declared parent | Parent exists? |
|---|---|---|
| `backend/data/providers/AGENTS.md` | `backend/data/AGENTS.md` | No |
| `backend/domain/evolution/AGENTS.md` | `backend/domain/AGENTS.md` | No |
| `backend/domain/genome/AGENTS.md` | `backend/domain/AGENTS.md` | No |
| `backend/monitoring/grafana/AGENTS.md` | `backend/monitoring/AGENTS.md` | No |
| `backend/db/AGENTS.md` | `backend/AGENTS.md` | No |
| `frontend/src/components/hft/AGENTS.md` | `frontend/src/components/AGENTS.md` | No |
| `docs/architecture/AGENTS.md` | `docs/AGENTS.md` | No |
| `docs/runbook/AGENTS.md` | `docs/AGENTS.md` | No |

**Fix:** Create all missing intermediate AGENTS.md files before any other work. The hierarchy must be navigable top-down.

---

### P0 — `backend/core/` has no AGENTS.md

`backend/core/` contains 115 files — the trading engine, risk manager, circuit breakers, AGI orchestration, settlement, scheduler, and more. It is the most-edited directory in the codebase and has zero agent documentation.

**Fix:** Create `backend/core/AGENTS.md` covering:
- The distinction between execution infrastructure (auto_trader, strategy_executor, risk_manager) and AGI lifecycle (autonomous_promoter, agi_health_check, agi_orchestrator)
- Files that must never be edited without an ADR: `risk_manager.py`, `circuit_breaker.py`, `settlement.py`
- The `botstate_mutex` pattern — always acquire before BotState read-modify-write
- Which schedulers own which jobs (scheduler.py job registry)
- Safe vs dangerous files in the directory

---

### P1 — Strategy governance data is stale and contradictory

The root AGENTS.md "Strategy Governance" section lists `copy_trader`, `weather_emos`, `whale_frontrun`, `whale_pnl_tracker` as active strategies. These live in `backend/modules/` (infra modules), not `backend/strategies/`. This directly contradicts the rule stated two lines above: "alpha strategies go in `backend/strategies/`."

Additionally, these files exist in `backend/strategies/` with no governance status documented anywhere:
- `bond_scanner.py`
- `cex_pm_leadlag.py`
- `cross_market_arb.py`
- `line_movement_detector.py`
- `market_maker.py`
- `agi_meta_strategy.py`

**Fix:**
1. Clarify in root AGENTS.md that `copy_trader`, `weather_emos`, `whale_frontrun`, `whale_pnl_tracker` are module-resident strategies (infra layer) and explain why they live in `backend/modules/` rather than `backend/strategies/`.
2. Add governance status (active/disabled/experimental) for all 6 undocumented strategy files.
3. Add a note that the strategy list in AGENTS.md is a snapshot — the authoritative source is `StrategyConfig` in the database.

---

### P1 — `scripts/` is ungoverned

`scripts/` contains a mix of:
- **Safe operational scripts:** `health-check.sh`, `backup-cron.sh`, `seed_backtest_data.py`
- **Destructive one-off scripts:** `fix_production_bugs.py`, `force_resettle.py`, `FIXES_APPLIED.py`
- **Test scripts that belong elsewhere:** `test-dashboard.spec.ts`, `test_agi_e2e.py`, `test_circuit_breakers.py`
- **Production service files:** `polyedge.service`, `polyedge-backup.service`, `polyedge-backup.timer`

An agent has no way to distinguish safe from dangerous without reading every file.

**Fix:** Create `scripts/AGENTS.md` with:
- A table categorizing every script as: `operational` | `one-off` | `destructive` | `test` | `service-config`
- Explicit warning: one-off and destructive scripts should not be re-run; they document historical fixes
- Note that `*.service` and `*.timer` files are systemd units for production — do not modify without ops review

---

### P1 — Key backend subdirectories have no AGENTS.md

These directories have significant surface area and no documentation:

| Directory | File count | What's missing |
|---|---|---|
| `backend/strategies/` | 12 files | Strategy base class contract, how to add a new strategy, registry pattern |
| `backend/ai/` | 25+ files | LLM routing logic, debate engine usage, which models are used for what |
| `backend/api/` | 15+ files | Router structure, auth patterns, how to add an endpoint |
| `backend/models/` | 8 files | ORM model conventions, migration workflow |
| `backend/application/` | 3 subdirs | Genome compiler usage, AGI/meta/strategy application layer |
| `backend/agents/` | autoresearch | What the autoresearch agent does, when it runs |
| `backend/infrastructure/` | market_stream | Market stream architecture |
| `backend/services/` | MiroFish | MiroFish integration contract, mock vs live |

**Fix:** Create AGENTS.md for each. Minimum viable content per file: Purpose (2–3 sentences), Key Files table, one "For AI Agents" rule that prevents the most common mistake in that directory.

---

### P2 — Root AGENTS.md missing Alembic migration workflow

The root AGENTS.md mentions `alembic/` in the Subdirectories table but gives no guidance on how to use it. Agents adding new ORM models frequently skip migrations or run them incorrectly.

**Fix:** Add to root AGENTS.md "Working In This Directory":
```
- Database schema changes require an Alembic migration: `alembic revision --autogenerate -m "description"` then `alembic upgrade head`. Never modify existing migration files.
```

---

### P2 — No machine-readable rule files

No `.cursorrules`, `CLAUDE.md`, `.ona/skills/`, or `.github/copilot-instructions.md` exist. Agents using tools that support these formats (Cursor, Claude Code, Copilot) get no structured rules — they rely entirely on the agent reading AGENTS.md manually.

**Fix (optional, low priority):** Create `.cursorrules` or `CLAUDE.md` at the repo root that mirrors the critical rules from root AGENTS.md in a format those tools auto-inject. Content should be a condensed version (never commit `.env`, doc sync is mandatory, shadow mode for live tests, botstate mutex pattern).

---

### P3 — `backend/monitoring/grafana/AGENTS.md` parent link is wrong

Declares `<!-- Parent: ../../AGENTS.md -->` which resolves to `backend/AGENTS.md`. The correct parent for a file at `backend/monitoring/grafana/` is `backend/monitoring/AGENTS.md`.

**Fix:** Change the parent comment to `<!-- Parent: ../AGENTS.md -->` and create `backend/monitoring/AGENTS.md`.

---

## Implementation Order

Work in this order to avoid creating files that reference other missing files:

1. **Create tier-1 missing files** (directly referenced from root):
   - `backend/AGENTS.md`
   - `frontend/AGENTS.md`
   - `docs/AGENTS.md`
   - `tests/AGENTS.md`
   - `scripts/AGENTS.md`
   - `backend/modules/AGENTS.md`

2. **Create tier-2 missing files** (referenced from tier-1):
   - `backend/core/AGENTS.md` ← highest priority content
   - `backend/strategies/AGENTS.md`
   - `backend/ai/AGENTS.md`
   - `backend/api/AGENTS.md`
   - `backend/models/AGENTS.md`
   - `backend/data/AGENTS.md`
   - `backend/domain/AGENTS.md`
   - `backend/monitoring/AGENTS.md`
   - `backend/application/AGENTS.md`
   - `backend/services/AGENTS.md`
   - `backend/repositories/AGENTS.md`
   - `backend/agents/AGENTS.md`
   - `backend/infrastructure/AGENTS.md`
   - `frontend/src/components/AGENTS.md`

3. **Fix root AGENTS.md content**:
   - Correct strategy governance section (stale list, contradictory module placement)
   - Add undocumented strategies with governance status
   - Add Alembic migration workflow note
   - Add note that strategy list is a snapshot; DB is authoritative

4. **Fix leaf AGENTS.md parent links**:
   - `backend/monitoring/grafana/AGENTS.md`: `../../AGENTS.md` → `../AGENTS.md`

5. **Optional: machine-readable rules**:
   - Create `CLAUDE.md` or `.cursorrules` with condensed critical rules

---

## AGENTS.md Template

All new files should follow this structure:

```markdown
<!-- Parent: {relative path to parent AGENTS.md} -->
<!-- Generated: YYYY-MM-DD | Updated: YYYY-MM-DD -->

# {directory path}

## Purpose

{2–3 sentences. What this directory contains and why it exists.}

## Key Files

| File | Description |
|------|-------------|
| `filename.py` | One-line description |

## Subdirectories (if any)

| Directory | Purpose |
|-----------|---------|
| `subdir/` | One-line description (see `subdir/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- {Most important constraint or gotcha — the thing that causes bugs if ignored}
- {Second most important}

### Testing Requirements
- {How to test changes in this directory}

### Common Patterns
- {Canonical usage pattern with code example if helpful}

## Dependencies

### Internal
- `module.path` — what it provides

### External
- `package` — what it's used for
```

Omit sections that don't apply (e.g. no Subdirectories section for leaf directories). Do not pad with obvious content.
