# HFT Pipeline Wiring — Deferred Debt Tracking

**Created:** 2026-07-28 | **Updated:** 2026-07-28
**Source:** `.sisyphus/plans/system-health-comprehensive.md` → Task 14

## Current State

The HFT subsystem exists but was DISCONNECTED from the main trading pipeline.
All 14 strategies go through the 60s-polling `scan_and_trade_job()`.

### Wired (2026-07-28 session)

| Component | Status | Notes |
|-----------|--------|-------|
| `HFTExecutor` (`backend/core/hft_executor.py`) | ✅ Built, idle | 314 lines, idempotency, circuit breaker, fill monitoring |
| Per-asset locks | ✅ Done | `_trade_locks: dict[str, asyncio.Lock]` in `strategy_executor.py` |
| Async CLOB path | ✅ Done | `_execute_decision_live_clob` uses direct async, no `asyncio.to_thread` |
| `OrderbookRouter` | ✅ Built, running | Created/started in `scheduler.py` |
| `HRiskManager` (`backend/core/risk/risk_manager_hft.py`) | ✅ Built | 238 lines |
| `types_hft` (`backend/strategies/types_hft.py`) | ✅ Built | HFTSignal, HFTExecution, HFTStrategyConfig |
| `hft_metrics` (`backend/monitoring/hft_metrics.py`) | ✅ Built | 251 lines |
| `slippage` (`backend/core/slippage.py`) | ✅ Built | 73 lines |
| **HFT fast path** in `execute_decision()` | ✅ Wired | `_hft_enabled()` check + `_execute_hft_path()` at top of function |
| **HFT_ENABLED env var** | ✅ Already in config.py | `settings.HFT_ENABLED` at line 423, default `True` |
| **OrderbookRouter → HFT trigger handler** | ✅ Wired | `_subscribe_hft_trigger()` registered in `scheduler.py` startup section |
| **HFT config params in main settings** | ✅ Already present | All HFT scanner/execution/whale/arb/latency params at lines 837-871 |
| Tests | ✅ Pass | 165/166 passing (1 pre-existing `test_max_trades_per_cycle` timeout) |

### NOT Yet Wired

| Component | Status | Priority | Notes |
|-----------|--------|----------|-------|
| `hft_signal_gen.py` | ✅ Implemented (639 lines) | 8 classes: `HFTSignalGenerator`, `BaseDetector`, 5 strategy detectors, `DetectorConfig` |
| `latency_optimizer.py` | ✅ Implemented (714 lines) | 8 classes: `LatencyOptimizer`, `DNSCache`, `ConnectionPreWarmer`, `EventLoopTuner`, `LatencyTracker`, `AutoTuner`, `EndpointConfig`, `LatencySample` |
| **HFT pipeline integration** | ✅ Wired | Both modules autostart from `scheduler.py` when `HFT_ENABLED=true` |

### What Was Done (2026-07-28)

1. **HFT fast path in `execute_decision()`** — Added `_hft_enabled()` helper and `_execute_hft_path()` async function in `strategy_executor.py`. When a decision dict has `hft=True` and `settings.HFT_ENABLED` is true, the decision routes through `HFTExecutor` which handles:
   - Per-asset `asyncio.Lock()` (not global)
   - `HRiskManager` risk validation
   - Idempotency check (30s TTL)
   - CLOB order placement via direct async
   - Fill monitoring via event bus
   - Fallback to standard path on any exception

2. **OrderbookRouter → strategy trigger** — Added `_subscribe_hft_trigger()` in `scheduler.py`. Subscribes to `orderbook_update` events via the event bus. On significant price movement (> `HFT_SCANNER_MIN_EDGE`), builds a decision dict with `hft=True` and calls `execute_decision()`. Includes 1s per-market debounce.

3. **Test fix** — Updated `test_orderbook_router.py::test_circuit_breaker_integration` to match actual config values (`failure_threshold==20`, `recovery_timeout==30` instead of stale 5/60).

### Implementation Approach

- **Fast path detection**: `decision.get("hft") or decision.get("hft_candidate")` flag — lightweight, doesn't require strategy code changes. Strategies can opt-in by setting `hft=True` on their decision dict.
- **Graceful fallback**: If `HFTExecutor.execute()` fails for any reason, the function returns `None` (not exception) and the caller's retry logic handles it.
- **Conservative by default**: `HFT_ENABLED=True` can be set to `False` in `.env` to disable entirely. The HFT trigger handler also checks this gate.

### Dependency: `config_hft.py`

`backend/config_hft.py` contains Pydantic-organized HFT config views. All values already exist as flat env vars in `backend/config.py`:
- `HFT_SCANNER_*` — scanner params (parallel_limit, max_markets, stale_threshold, min_edge, etc.)
- `HFT_EXECUTION_*` — execution params (auto_execute, position_size, max_position, idempotency_ttl)
- `HFT_WHALE_*` — whale detection
- `HFT_ARB_*` — arbitrage params
- `HFT_LATENCY_*` — latency thresholds (max_scan=1000ms, max_execution=50ms, alert=100ms, cache_ttl=1s)

### Must NOT Do
- Remove slow path (REST polling) — keep as fallback
- Bypass RiskManager in fast path
- Enable HFT path in LIVE mode without paper testing
- Remove idempotency check
