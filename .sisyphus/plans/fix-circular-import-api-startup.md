# Fix Circular Import Deadlock in Strategy Loading + Merge PR #94

## TL;DR

> **Quick Summary**: Extract `load_all_strategies()` from `registry.py` into new `loader.py` to break circular import deadlock blocking API startup. Merge PR #94 after fix. Verify API starts on port 8100 and trades execute.

> **Deliverables**:
> - `backend/strategies/loader.py` — new module with `load_all_strategies()`, `_skip_module()`, `_discover_flat()`, `_discover_recursive()`
> - `backend/strategies/registry.py` — remove moved functions, export what loader needs
> - `backend/api/lifespan.py` — update import
> - PR #94 merged to `main` (safe, non-conflicting)

> **Estimated Effort**: Short
> **Parallel Execution**: NO - sequential (fix → merge → restart → verify)
> **Critical Path**: loader.py creation → lifespan import update → PR merge → restart → verify

---

## Context

### Original Request
Fix all remaining bugs preventing PolyEdge from executing live and paper trades. Merge open PR #94 safely.

### Research Findings

**Root Cause Diagnosed**: Circular import deadlock in strategy loading.

```
lifespan() → load_all_strategies() [registry.py:283]
  → importlib.import_module(strategy_module)
    → BaseStrategy.__init_subclass__() [base.py:250]
      → from backend.strategies.registry import _auto_register
        → DEADLOCK: registry.py still executing load_all_strategies()
```

`_auto_register` is already imported in `registry.py` module-level code — the circular import comes from strategy modules trying to re-import `registry` while `registry` is mid-execution.

**Individual imports work** — each strategy module imports fine alone. Only `load_all_strategies()` batch import hangs.

**PR #94 is clean** — adds `RedisLogHandler`, `_redis_log_bridge()`, `configure_logging()` call in lifespan, `SystemLogsTab`. No overlap with our `database.py` or `config.py` changes. No conflict with the circular import fix.

---

## Work Objectives

### Core Objective
Eliminate circular import deadlock so API starts on port 8100. Merge PR #94 safely. Verify trades execute.

### Concrete Deliverables
- `backend/strategies/loader.py` with `load_all_strategies()` + helpers
- `registry.py` slimmed down
- PR #94 merged
- polyedge-api listening on port 8100
- New trade_attempts in PostgreSQL

### Definition of Done
- [ ] `curl http://127.0.0.1:8100/api/v1/health` returns 200
- [ ] PM2 shows polyedge-api uptime > 30 seconds (no restart loop)
- [ ] No circular import errors in API logs
- [ ] PR #94 merged to main
- [ ] At least 1 new trade_attempt in PostgreSQL after bot cycle

### Must Have
- Strategy loading completes without deadlock
- API serves requests on port 8100
- PR #94 changes integrated without regression

### Must NOT Have (Guardrails)
- Do NOT modify `base.py` or any strategy file (fix at registry level only)
- Do NOT change the auto-registration mechanism (`__init_subclass__`)
- Do NOT remove `_auto_register` or `BaseStrategy` from `registry.py`
- Do NOT split the fix into multiple PRs — single atomic commit
- Do NOT merge PR #94 before the circular import fix

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: NO (none cover strategy loading)
- **Framework**: N/A

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/`.

- **API/Backend**: Bash (curl) — Send requests, assert status + response fields
- **CLI**: Bash — Run commands, check output, check process status

---

## Execution Strategy

### Sequential Execution

```
Step 1: Create loader.py + update registry.py + update lifespan.py
  ↓
Step 2: Commit + push → restart API → verify port 8100
  ↓
Step 3: Merge PR #94 → restart API → verify no regression
  ↓
Step 4: Restart bot → wait for cycle → verify trade_attempts
  ↓
Step 5: Verify live + paper trade execution
```

### Critical Path
Step 1 → Step 2 → Step 3 → Step 4 → Step 5

---

## TODOs

- [ ] 0. PostgreSQL safety audit — verify zero SQLite/PostgreSQL mixed-up code remains

  **What to do**:
  - Verify all SQLite-specific code is properly gated behind dialect checks
  - Confirm `configure_sqlite_wal()` returns early on PostgreSQL engine (dialect check at L63)
  - Confirm `_set_sqlite_busy_timeout()` returns early on PostgreSQL (dialect check at L108)
  - Confirm `_attempt_data_recovery()` only runs on SQLite URLs (L1162 check)
  - Confirm all `PRAGMA` statements are in SQLite-only code paths
  - Confirm ORM `DateTime` and `Boolean` Column types work correctly with PostgreSQL (SQLAlchemy handles mapping)
  - Confirm `_TS_TYPE = "TIMESTAMP"` for PostgreSQL (verified working)
  - Confirm no raw `sqlite3` imports in non-gated code
  - Confirm `init_db` repair path only triggers "database disk image is malformed" (SQLite-specific error)
  - Verify no `IFNULL`, `strftime`, `last_insert_rowid`, or other SQLite-specific SQL functions in production code

  **Must NOT do**:
  - Do NOT remove SQLite support — it's needed for tests and fallback mode
  - Do NOT change gated code — gates are already correct

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Read-only verification task
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (runs independently before any code changes)
  - **Parallel Group**: Pre-flight (verification only, runs before Task 1)
  - **Blocks**: Task 4 (must pass before API restart — gates all further work)
  - **Blocked By**: None

  **References**:
  - `backend/models/database.py:36` — `_is_postgres = settings.is_postgres`
  - `backend/models/database.py:44-56` — Engine kwargs branching on `_is_postgres`
  - `backend/models/database.py:61-80` — `configure_sqlite_wal()` with dialect check
  - `backend/models/database.py:105-112` — `_set_sqlite_busy_timeout()` with dialect check
  - `backend/models/database.py:1153-1162` — `_attempt_data_recovery()` with URL check
  - `backend/models/database.py:60` — `_TS_TYPE` constant
  - `backend/alembic/versions/20260421_comprehensive_schema_sync.py:26` — Alembic migration SQLite check

  **Acceptance Criteria**:
  - [ ] Zero un-gated SQLite-specific code paths in production execution flow
  - [ ] `settings.is_postgres == True` when DATABASE_URL is PostgreSQL
  - [ ] `configure_sqlite_wal` skips all PRAGMA on PostgreSQL
  - [ ] No raw `sqlite3` import executes on PostgreSQL path

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify PostgreSQL engine creation skips SQLite PRAGMA
    Tool: Bash
    Preconditions: DATABASE_URL resolves to PostgreSQL
    Steps:
      1. cd /home/openclaw/projects/polyedge && python -c "
         import sys; sys.path.insert(0, 'backend')
         from dotenv import load_dotenv; load_dotenv(override=False)
         from config import settings
         assert 'postgresql' in settings.DATABASE_URL, f'Expected PG, got {settings.DATABASE_URL[:50]}'
         assert settings.is_postgres == True, f'Expected is_postgres=True, got {settings.is_postgres}'
         from models.database import engine
         assert engine.url.get_dialect().name == 'postgresql', f'Expected postgresql dialect, got {engine.url.get_dialect().name}'
         print('ALL_CHECKS_PASSED')
         "
      2. Assert stdout contains "ALL_CHECKS_PASSED"
    Expected Result: Engine is PostgreSQL, dialect is postgresql, is_postgres is True
    Failure Indicators: Dialect name not 'postgresql', is_postgres False, DATABASE_URL still SQLite
    Evidence: .sisyphus/evidence/task-0-pg-verified.txt
  ```

  **Commit**: NO (verification only)

- [ ] 1. Create `backend/strategies/loader.py` — extract strategy loading functions

  **What to do**:
  - Create new file `backend/strategies/loader.py`
  - Copy `_skip_module()`, `_discover_flat()`, `_discover_recursive()`, `load_all_strategies()` from `registry.py`
  - Keep implementation identical — just change module location
  - These functions import from `registry` for `STRATEGY_REGISTRY` and `BaseStrategy` — that's the correct direction (loader → registry, not registry → loader)

  **Must NOT do**:
  - Do NOT modify function logic — this is a pure extraction
  - Do NOT add new imports or dependencies
  - Do NOT change function signatures

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Pure code extraction, no logic changes
  - **Skills**: `[]`
  - **Skills Evaluated but Omitted**:
    - None needed — extract-and-copy task

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: Task 2
  - **Blocked By**: None

  **References**:
  - `backend/strategies/registry.py:201-294` — Source functions to extract (`_skip_module`, `_discover_flat`, `_discover_recursive`, `load_all_strategies`)

  **Acceptance Criteria**:
  - [ ] File `backend/strategies/loader.py` exists with all 4 functions
  - [ ] `python -c "from backend.strategies.loader import load_all_strategies"` succeeds

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify loader.py imports correctly
    Tool: Bash
    Preconditions: Task 1 implementation complete, file exists
    Steps:
      1. cd /home/openclaw/projects/polyedge && python -c "
         import sys; sys.path.insert(0, 'backend')
         from dotenv import load_dotenv; load_dotenv(override=False)
         from backend.strategies.loader import load_all_strategies, _skip_module, _discover_flat, _discover_recursive
         print('ALL_IMPORTS_OK')
         "
      2. Assert stdout contains "ALL_IMPORTS_OK"
    Expected Result: All four functions importable from loader module
    Failure Indicators: ImportError, ModuleNotFoundError, AttributeError
    Evidence: .sisyphus/evidence/task-1-imports-ok.txt

  Scenario: Verify loader functions still work (discovery only, no import)
    Tool: Bash
    Preconditions: Task 1 complete, imports verified
    Steps:
      1. cd /home/openclaw/projects/polyedge && python -c "
         import sys, os; sys.path.insert(0, 'backend')
         os.chdir('/home/openclaw/projects/polyedge')
         from dotenv import load_dotenv; load_dotenv(override=False)
         from backend.strategies.loader import _discover_flat, _discover_recursive, _skip_module
         strategies = _discover_flat('backend.strategies', 'backend/strategies')
         modules = _discover_recursive('backend.modules', 'backend/modules')
         print(f'Strategies found: {len(strategies)}')
         print(f'Modules found: {len(modules)}')
         for s in strategies: print(f'  STRATEGY: {s}')
         for m in modules: print(f'  MODULE: {m}')
         "
      2. Assert strategies count > 0 and modules count > 0
    Expected Result: Discovery finds at least 5 strategy modules and 4+ module-resident strategies
    Failure Indicators: Zero strategies or modules found, wrong paths
    Evidence: .sisyphus/evidence/task-1-discovery.txt
  ```

  **Commit**: YES
  - Message: `fix: extract strategy loading to separate loader module (breaks circular import)`
  - Files: `backend/strategies/loader.py`

- [ ] 2. Update all 7 import sites to use `backend.strategies.loader` instead of `registry`

  **What to do**:
  - Update each file's import from `from backend.strategies.registry import load_all_strategies` → `from backend.strategies.loader import load_all_strategies`
  - Files to update:
    1. `backend/models/database.py:1387` — inside `seed_default_data()` called by `init_db()`. **CRITICAL**: this is the actual API startup deadlock trigger (runs before the lifespan.py call at L457)
    2. `backend/api/lifespan.py:24` — API lifespan startup
    3. `backend/core/orchestrator.py:87` — bot process startup
    4. `backend/api/system.py:1468` — runtime system endpoints
    5. `backend/api/backtest.py:15-18` — backtest API (module-level import)
    6. `backend/tests/test_performance_accuracy.py:14` — test
    7. `backend/tests/test_general_scanner.py:194,207,221` — test
    8. `backend/tests/test_comprehensive_integration.py:14` — test
  - In `registry.py`, also remove the `import os` and one `import pkgutil` (both only used by removed functions; lines 216 and 230). Keep `import os` at line 266 (used inside `load_all_strategies` which is being removed too) and `import importlib` at line 267 (only used in removed function)

  **Must NOT do**:
  - Do NOT change function call sites — only update the import path
  - Do NOT change test logic
  - Do NOT remove `STRATEGY_REGISTRY` import (many files import it separately from registry for read access)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Search-and-replace import paths across 8 files
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (must follow Task 1 creation of loader.py)
  - **Blocks**: Task 3
  - **Blocked By**: Task 1

  **References**:
  - `backend/strategies/loader.py` — New import target (created in Task 1)
  - All import sites listed above

  **Acceptance Criteria**:
  - [ ] `grep -rn 'from backend.strategies.registry import.*load_all_strategies' backend/api/ backend/core/ backend/models/ backend/strategies/ --include="*.py"` returns ZERO matches
  - [ ] `grep -rn 'from backend.strategies.loader import load_all_strategies' backend/api/ backend/core/ backend/models/ --include="*.py"` returns at least 5 matches
  - [ ] Registry module still importable: `python -c "from backend.strategies.registry import STRATEGY_REGISTRY, BaseStrategy"` succeeds

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify all production imports use loader
    Tool: Bash
    Preconditions: Task 2 complete
    Steps:
      1. cd /home/openclaw/projects/polyedge && grep -rn 'from backend.strategies.registry import.*load_all_strategies' backend/api/lifespan.py backend/models/database.py backend/core/orchestrator.py backend/api/system.py backend/api/backtest.py
      2. Assert exit code is 1 (no matches — zero files still import from registry)
      3. cd /home/openclaw/projects/polyedge && grep -rn 'from backend.strategies.loader import load_all_strategies' backend/api/lifespan.py backend/models/database.py backend/core/orchestrator.py backend/api/system.py backend/api/backtest.py
      4. Assert count of matches equals 5
    Expected Result: All production import sites use loader module
    Failure Indicators: Any production file still importing from registry
    Evidence: .sisyphus/evidence/task-2-all-imports.txt
  ```

- [ ] 3. Commit all changes, push, restart API, verify port 8100

  **What to do**:
  - Stage all changed files: `backend/strategies/loader.py` (new), `backend/strategies/registry.py` (cleaned), plus all 8 files with import path updates
  - Single commit: `fix: extract strategy loading to loader module (breaks circular import deadlock)`
  - Push to `origin/main`
  - Flush PM2 logs: `pm2 flush polyedge-api`
  - Restart API: `pm2 restart polyedge-api --update-env`
  - Wait 30 seconds
  - Check if port 8100 is listening
  - Check logs for "API Lifespan startup completed" message

  **Must NOT do**:
  - Do NOT restart the bot yet (verify API independently first)
  - Do NOT skip the 30-second wait

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Git + PM2 operations, no code changes
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: Task 5
  - **Blocked By**: Task 3

  **References**:
  - `backend/strategies/loader.py` — New module (created Task 1)
  - `backend/strategies/registry.py` — Updated (Task 2)
  - `backend/api/lifespan.py` — Updated (Task 3)

  **Acceptance Criteria**:
  - [ ] Commit pushed to `origin/main`
  - [ ] `pm2 status` shows polyedge-api online with uptime > 30s
  - [ ] `ss -tlnp | grep 8100` shows port 8100 listening
  - [ ] `curl -s http://127.0.0.1:8100/api/v1/health` returns HTTP 200
  - [ ] `pm2 logs polyedge-api --lines 20` contains "API Lifespan startup completed"

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify API healthy after fix
    Tool: Bash
    Preconditions: Tasks 1-3 complete, code pushed, API restarted, 30s waited
    Steps:
      1. /usr/bin/ss -tlnp 2>/dev/null | /bin/grep 8100
      2. Assert output shows LISTEN on port 8100
      3. /usr/bin/curl -s -m 10 http://127.0.0.1:8100/api/v1/health
      4. Assert response contains "ok" or returns HTTP 200
    Expected Result: Port 8100 listening, health endpoint responds
    Failure Indicators: Port not listening, curl timeout, non-200 response
    Evidence: .sisyphus/evidence/task-4-api-healthy.txt

  Scenario: Verify no circular import errors in logs
    Tool: Bash
    Preconditions: API healthy
    Steps:
      1. pm2 logs polyedge-api --lines 50 --nostream 2>&1 | grep -i "circular\|deadlock\|cannot import\|ImportError"
      2. Assert no output (zero matches for error patterns)
    Expected Result: Zero circular import or deadlock errors
    Failure Indicators: Any circular import error, ImportError, cannot import messages
    Evidence: .sisyphus/evidence/task-4-no-errors.txt

  Scenario: Verify strategy registry populated
    Tool: Bash
    Preconditions: API healthy
    Steps:
      1. cd /home/openclaw/projects/polyedge && python -c "
         import sys; sys.path.insert(0, 'backend')
         from dotenv import load_dotenv; load_dotenv(override=False)
         from backend.strategies.registry import STRATEGY_REGISTRY
         print(f'Registry count: {len(STRATEGY_REGISTRY)}')
         print(f'Keys: {sorted(STRATEGY_REGISTRY.keys())}')
         "
      2. Assert registry count > 10
      3. Assert 'universal_scanner' and 'agi_orchestrator' in keys
    Expected Result: At least 10 strategies registered, key strategies present
    Failure Indicators: Registry empty or < 5 entries, key strategies missing
    Evidence: .sisyphus/evidence/task-4-registry.txt
  ```

  **Commit**: YES
  - Message: `fix: extract strategy loading to separate loader module (breaks circular import)`
  - Files: `backend/strategies/loader.py`, `backend/strategies/registry.py`, `backend/api/lifespan.py`

- [ ] 5. Merge PR #94 (Unified Logs Tab)

  **What to do**:
  - Fetch PR #94 branch: `git fetch origin cto/add-system-logs-sse`
  - Check if merge would succeed: `git merge --no-commit --no-ff origin/cto/add-system-logs-sse`
  - If conflict: resolve in `lifespan.py` (only likely conflict point — PR adds `configure_logging` + `_redis_log_bridge` before yield; our code is at the same spot)
  - Run `python -c "from backend.api.lifespan import lifespan"` to verify no import errors
  - Commit merge
  - Push to origin/main
  - Restart API: `pm2 restart polyedge-api --update-env`
  - Wait 30 seconds
  - Verify port 8100 still listening
  - Verify no new errors in logs

  **Must NOT do**:
  - Do NOT skip merge validation (import check)
  - Do NOT merge if conflict resolution breaks the circular import fix

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Git merge + verification
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: Task 6
  - **Blocked By**: Task 4

  **References**:
  - PR #94 branch: `cto/add-system-logs-sse`
  - Files affected: `backend/api/lifespan.py`, `backend/monitoring/structured_logger.py`, `frontend/src/hooks/useSSEEvents.ts`, `frontend/src/components/admin/SystemLogsTab.tsx`

  **Acceptance Criteria**:
  - [ ] PR #94 merged to main
  - [ ] API started on port 8100 after merge
  - [ ] `curl -s http://127.0.0.1:8100/api/v1/health` returns 200
  - [ ] No merge conflicts (or resolved cleanly)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify API healthy after PR merge
    Tool: Bash
    Preconditions: PR #94 merged, API restarted, 30s waited
    Steps:
      1. /usr/bin/ss -tlnp 2>/dev/null | /bin/grep 8100
      2. Assert output shows LISTEN
      3. /usr/bin/curl -s -m 10 http://127.0.0.1:8100/api/v1/health
      4. Assert response contains "ok" or returns HTTP 200
    Expected Result: API healthy after merge
    Failure Indicators: Port not listening, non-200 response
    Evidence: .sisyphus/evidence/task-5-post-merge-healthy.txt

  Scenario: Verify no lifespan errors after merge
    Tool: Bash
    Preconditions: API healthy post-merge
    Steps:
      1. pm2 logs polyedge-api --lines 30 --nostream 2>&1 | grep -i "error\|traceback\|exception\|cannot import"
      2. Assert only expected "could not add genome_registry" warnings (non-fatal migration warnings)
    Expected Result: No new errors introduced by merge
    Failure Indicators: New import errors, lifespan startup failures
    Evidence: .sisyphus/evidence/task-5-no-new-errors.txt
  ```

  **Commit**: YES (merge commit)
  - Message: `Merge PR #94: unified system logs tab with RedisLogHandler and SSE bridge`

- [ ] 6. Restart bot, verify trade execution

  **What to do**:
  - Restart bot: `pm2 restart polyedge-bot --update-env`
  - Wait for at least one full cycle (5+ minutes)
  - Check PostgreSQL for new trade_attempts: `psql postgresql://polyedge:polyedge123@localhost:5432/polyedge -c "SELECT strategy_name, mode, status, created_at FROM trade_attempts ORDER BY created_at DESC LIMIT 20"`
  - Verify at least 1 new record with `created_at` after restart time
  - Check for EXECUTED status trades (both paper and live modes)

  **Must NOT do**:
  - Do NOT consider task complete if zero new trade_attempts after 10 minutes
  - Do NOT skip checking both paper AND live trades

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: PM2 ops + DB query verification
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: None (final task)
  - **Blocked By**: Task 5

  **References**:
  - PostgreSQL: `postgresql://polyedge:polyedge123@localhost:5432/polyedge`
  - `backend/core/risk_manager.py:505-525` — confidence threshold logic
  - Previous trade_attempts: 411,373 total, last at May 10 10:58

  **Acceptance Criteria**:
  - [ ] PM2 shows polyedge-bot online with uptime > 2 minutes
  - [ ] At least 1 new trade_attempt in PostgreSQL with `created_at` after restart
  - [ ] At least 1 paper mode trade_attempt
  - [ ] Optional: at least 1 EXECUTED status trade (depends on market conditions)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify bot running and producing trade attempts
    Tool: Bash
    Preconditions: Bot restarted, waited 8+ minutes for cycles
    Steps:
      1. pm2 status 2>/dev/null | grep polyedge-bot
      2. Assert status is "online" and uptime > 2m
      3. PGPASSWORD=polyedge123 psql -h localhost -U polyedge -d polyedge -t -c "SELECT COUNT(*) FROM trade_attempts WHERE created_at > NOW() - INTERVAL '10 minutes'"
      4. Assert count > 0
    Expected Result: Bot online, new trade_attempts in last 10 minutes
    Failure Indicators: Bot crashed, zero new trade_attempts
    Evidence: .sisyphus/evidence/task-6-new-attempts.txt

  Scenario: Check trade attempt modes and statuses
    Tool: Bash
    Preconditions: New trade_attempts confirmed
    Steps:
      1. PGPASSWORD=polyedge123 psql -h localhost -U polyedge -d polyedge -c "SELECT mode, status, COUNT(*) FROM trade_attempts WHERE created_at > NOW() - INTERVAL '10 minutes' GROUP BY mode, status ORDER BY mode, status"
      2. Assert output includes both "paper" and "live" modes
    Expected Result: Both paper and live mode trade_attempts present
    Failure Indicators: Only one mode producing attempts, no EXECUTED attempts
    Evidence: .sisyphus/evidence/task-6-modes.txt
  ```

  **Commit**: NO (operational task)

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files in .sisyphus/evidence/.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Verify `loader.py` module structure is clean: no logic changes from source, no new imports beyond what was in registry.py, function signatures identical. Verify `registry.py` has no dangling references. Verify `lifespan.py` import is correct path.
  Output: `Loader [CLEAN/N issues] | Registry [CLEAN/N issues] | Lifespan [CLEAN/N issues] | VERDICT`

- [ ] F3. **Operational Verification** — `quick`
  From clean state, verify: API starts on port 8100, health endpoint responds, no restart loop, strategy registry populated, bot producing trade_attempts, both paper and live modes active.
  Output: `API [HEALTHY/DOWN] | Bot [RUNNING/STOPPED] | Attempts [N new] | Modes [N active] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  Verify PR #94 changes are intact after merge: `RedisLogHandler` in structured_logger.py, `_redis_log_bridge` in lifespan.py, `configure_logging` call in lifespan, `SystemLogsTab.tsx` exists, event mapping updated. Verify our changes didn't regress: `_TS_TYPE` still in database.py, loader.py exists, circular import resolved.
  Output: `PR94 [INTACT/N issues] | Our fixes [INTACT/N issues] | Cross-contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

- **1**: `fix: break circular import in strategy loading by extracting loader module`
- **2**: `merge: PR #94 - unified system logs tab` (merge commit)

---

## Success Criteria

### Verification Commands
```bash
curl -s http://127.0.0.1:8100/api/v1/health  # Expected: {"status":"ok"}
pm2 status | grep polyedge-api  # Expected: uptime > 30s, no restart loop
```

### Final Checklist
- [ ] API starts without circular import deadlock
- [ ] Strategy registry populated after startup
- [ ] PR #94 merged, no conflicts
- [ ] Trade attempts being created in PostgreSQL
- [ ] Paper trade executes successfully
- [ ] Live trade executes successfully
