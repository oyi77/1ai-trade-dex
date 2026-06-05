# PolyEdge Settlement / Scheduler Deprecation Audit

Use this when a task says "do all that" on drift/debt cleanup for PolyEdge.

## Verified Active Paths
- Scheduler shim: `backend/core/scheduler.py` re-exports `backend/core/scheduling/scheduler.py`
- Live scheduling jobs: `backend/core/scheduling/scheduling_strategies.py`
- Settlement imports are routed through `backend/core/settlement/settlement.py` → `backend/core/settlement/settlement_helpers.py`
- New reconciler path: `backend/core/wallet/wallet_reconciliation.py`, `backend/core/wallet/bankroll_reconciliation.py`

## Drift Checklist
1. Fix math/threshold errors in strategy logic only (CexPmLeadLag already fixed).
2. Confirm DB counters increment (`markets_scanned`, `decisions_recorded`) where needed.
3. Do NOT reorganize cross-module imports without an explicit import error.
4. Preserve working tests while refactoring.

## Arb Integration Checklist
- Keep `min_market_distance` parameterized, not hardcoded.
- Ensure `_DEFAULT_FEES` contains any provider used in production (`polymarket`, `kalshi`, `sxbet`).
- Verify `record_decision` / `DecisionLog` paths remain intact after DB changes.
