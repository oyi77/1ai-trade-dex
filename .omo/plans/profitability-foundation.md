# Profitability Foundation Plan

## Requirements

- Make paper-trading profitability harder to inflate through impossible fills.
- Preserve multi-platform support; do not hardcode live Polymarket-only behavior into generic strategy logic.
- Add verifiable gates before promoting or trusting strategy profitability.
- Prefer dry-run/audit tooling before mutating historical PnL.

## Current State

- `backend/core/strategy_executor.py::_execute_decision_paper_or_kalshi()` routes paper orders through `PaperSlippageSimulator` and persists fee/slippage/fill fields through `_record_trade()`.
- `backend/core/paper_slippage.py::simulate_fill()` applies configurable slippage, fee, and a minimum total-depth check, but it does not cap order size as a percentage of available depth and does not penalize extreme longshot prices.
- `backend/core/agi_promotion_pipeline.py` has simple trade count / win-rate gates but does not evaluate realistic EV, outlier dependence, or liquidity-adjusted performance.
- `backend/scripts/reconcile_bot_state.py` reconciles derived `BotState` caches, but no dedicated dry-run script audits historical paper PnL after fee/fill formula changes.

## Approach Decision

### Selected: vertical profitability-foundation slices

1. Harden paper fill simulation first.
2. Add historical paper PnL audit/recalculation dry-run second.
3. Add promotion gates that consume the audited metrics third.

This order prevents promoting strategies based on optimistic simulation artifacts.

## Execution Plan

### Phase 1: Paper fill realism gate

- Add `PAPER_MAX_DEPTH_CONSUMPTION_PCT` runtime setting.
- Add `PAPER_LONGSHOT_SLIPPAGE_MULTIPLIER` runtime setting.
- Reject paper orders that consume too much known orderbook depth.
- Penalize slippage when entry price is near 0 or 1.
- Verify with focused unit tests for rejection and longshot penalty.

### Phase 2: Historical PnL audit

- Add dry-run script that recomputes settled paper trade PnL with current `calculate_pnl()`.
- Report current vs recomputed PnL, outlier contribution, and top mismatches.
- Do not mutate DB without an explicit `--apply` mode and backup guidance.

### Phase 3: Promotion gates

- Add profitability quality metrics: sample size, profit factor, max drawdown, outlier contribution, and liquidity rejection rate.
- Block live promotion when a small number of outliers explain most PnL.
- Integrate with `AGIPromotionPipeline` or a reusable metrics helper consumed by it.

## Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Paper trades become too conservative | Medium | Runtime settings keep thresholds adjustable. |
| Existing tests assume old slippage | Medium | Add focused tests and run targeted suite. |
| Historical DB PnL changes surprise dashboard users | High | Phase 2 starts dry-run only. |
| Promotion gates reject useful strategies | Medium | Gate on metrics and explain rejection reasons. |

## Verification

- `venv/bin/python -m pytest backend/tests/test_paper_slippage.py -q`
- Existing accounting suite remains green after Phase 1.
- Diagnostics on modified files.
