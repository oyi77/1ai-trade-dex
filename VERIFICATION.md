# Verification Checklist — PolyEdge

Run these on your local dev machine (same environment as `backend/tests`).

## 1) Targeted tests (expected green)
```
pytest backend/tests/test_cex_pm_leadlag_enhanced.py backend/tests/test_settlement.py backend/tests/test_integration_settlement_fills.py backend/tests/test_bankroll_reconciliation.py -q
```
Expected: **51 passed**.

## 2) Scheduler imports + config (validate without DB round-trips)
```
python - <<'PY'
import importlib
mods = [
	"backend.core.scheduling.scheduler",
	"backend.core.scheduling.scheduling_strategies",
	"backend.core.settlement.settlement",
	"backend.core.settlement.settlement_helpers",
	"backend.data.wallet_history",
	"backend.data.arb_opportunity_scanner",
	"backend.strategies.probability_arb",
	"backend.strategies.market_maker",
]
for m in mods:
	importlib.import_module(m)
	print("OK", m)
PY
```
Expected: all `OK`, then exit 0.

## 3) Feature-gate behavior (no live trades)
Check in app config:
- `ARBITRAGE_DETECTOR_ENABLED = False`
- Scheduler intentionally does **not** register blocking wallet sync/verification jobs.
After toggle:
- `arbitrage_scan_job()` returns immediately when disabled.
- `wallet_reconciler_job()` still runs and uses async `bankroll_reconciliation` path, not the old blocking wallet sync path.

## 4) Cross-platform arb code path intact
Smoke check:
```
python - <<'PY'
from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced
from backend.strategies.unified_pm_arb import UnifiedPMArb
from backend.core.decisions import record_decision
from backend.core.arbitrage_detector import ArbitrageDetector
print('cross_market_arb_enhanced OK')
print('unified_pm_arb OK')
print('record_decision OK')
print('ArbitrageDetector OK')
PY
```

## 5) DB drift sanity (requires Postgres)
```
psql -U openclaw -d berkahkarya -c "select count(*) from trades where settled = false;"
```
Also inspect `backend.core.wallet.wallet_reconciliation.WalletReconciler.reconcile()` and `backend.core.wallet.bankroll_reconciliation.reconcile_bot_state()` as the authoritative drift paths.

## 6) Backtest vs live parity check
- `backend/core/backtester.py` uses `settlement_value` only from trade objects.
- `backend/core/pybroker_backtest.py` does the same.
- No divergence path in the files inspected today.
