# Silent `except: pass` Cleanup

**Status:** DEFERRED
**Created:** 2026-07-28
**Priority:** LOW (non-critical paths)

## Problem

~70+ locations in production code use `except: pass` without `logger.warning()` or `logger.exception()` before the pass. Most are in:
- asyncio task cancellation (standard pattern — `asyncio.CancelledError`)
- WebSocket timeout loops (standard pattern — `asyncio.TimeoutError`)
- DB rollback cleanup (rollback may fail if already closed)
- Optional dependency imports (`ImportError` expected)
- Temp file cleanup (`OSError` is non-fatal)

## Acceptance Criteria

1. All `except:` blocks in production (non-test, non-alembic) code have at minimum a `logger.debug()` or `logger.warning()` before `pass`
2. No silent error swallowing in these paths:
   - Trading execution (execute.py, strategy_executor.py)
   - Auth (auth.py)
   - Configuration loading (config.py, log.py)
   - Plugin registration (plugin_registry.py)

## Not Required

- Test files (tests swallow errors intentionally for coverage isolation)
- Alembic migrations (idempotent migration pattern is acceptable)

## Guidance

- `asyncio.CancelledError` / `asyncio.TimeoutError` → `logger.debug("Task cancelled/timeout")` is enough
- DB cleanup → `logger.debug("Rollback failed (expected if already closed): {e}")`
- ImportError → `logger.debug("Optional dependency not available: {e}")`
- Business logic → `logger.warning("Non-critical operation failed: {e}")` or `logger.exception()`
