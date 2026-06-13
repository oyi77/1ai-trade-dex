# ADR-018: Extend ADR-016's `total_loss_settlement_value` Fix to the Remaining `result="loss"` Force-Settle Branches

**Status:** Accepted
**Date:** 2026-06-13

## Context

ADR-016 fixed `scheduler.py::_cleanup_stale_trades_job`'s `stuck_paper`
branch (`force_closed_unresolved`), which previously hardcoded `pnl=0.0`
alongside `result="loss"`. ADR-016 explicitly deferred four other branches
that had the *same* `calculate_pnl(trade, 0.0)` hardcode, reasoning that
"live trading is currently disabled... so it is out of scope":

- `settlement.py::settle_pending_trades` — `closed_unresolved` (position
  reconciliation, grace period exhausted)
- `settlement.py::settle_pending_trades` — `expired_unresolved`
  (`market_end_date` passed, no resolution after grace)
- `settlement.py::settle_pending_trades` — `stale_expired` (trade older
  than `STALE_TRADE_HOURS`, position confirmed gone on-chain)
- `settlement.py::_settle_btc_5min_trade` — `btc_5min_unresolved` (BTC 5-min
  market unresolved 24h after window close)

`calculate_pnl(trade, 0.0)` means "settlement_value=0.0", i.e. the NO/DOWN
outcome occurred. For a `direction="yes"/"up"` position that's a real loss
(negative pnl) — consistent with `result="loss"`. But for a
`direction="no"/"down"` position, `settlement_value=0.0` is a **win** for
that side, so `calculate_pnl` returns the WIN formula (positive pnl) while
`result="loss"` — the exact self-contradiction ADR-016 fixed for
`force_closed_unresolved`, just on different branches.

### This is no longer purely theoretical

`bond_scanner` is currently `enabled=true` for **live** trading
(`rehab_allocation_pct=0.25`, re-enabled 2026-06-12 07:30:40 — superseding
the "live trading disabled" assumption ADR-016 relied on to defer this).

Querying current trade data found 11 `bond_scanner` trades (10 distinct
positions; one market has two trades) with `result="loss"` and **positive**
`pnl`, all `direction="no"`, all settled via `closed_unresolved` or
`expired_unresolved`:

```
id     market                                                  entry  size     pnl   result  source
25753  will-matheus-cunha-score-a-goal-...-world-cup            0.230  5.000    3.85  loss    closed_unresolved
25700  will-luke-kornet-score-40-points-...                     0.908  5.776    0.53  loss    closed_unresolved
25699  (same market as 25700)                                   0.908  5.776    0.53  loss    closed_unresolved
25694  over-500m-committed-to-the-align-public-sale             0.988  5.050    0.06  loss    closed_unresolved
25693  will-morgan-stanley-fail-by-june-30-2026                 0.989  5.050    0.06  loss    closed_unresolved
25440  highest-temperature-in-denver-on-june-8-2026-92-93f      0.039  5.000    4.81  loss    expired_unresolved
25328  highest-temperature-in-guangzhou-on-june-8-2026-35corh.  0.010  5.000    4.95  loss    expired_unresolved
25265  highest-temperature-in-houston-on-june-7-2026-82-83f     0.016  5.000    4.92  loss    expired_unresolved
25087  highest-temperature-in-dallas-on-june-7-2026-94-95f      0.114  5.000    4.43  loss    expired_unresolved
24156  highest-temperature-in-atlanta-on-june-7-2026-76-77f     0.010  5.000    4.95  loss    expired_unresolved
```

All 11 rows have `settlement_value=0.0` — confirming they went through the
hardcoded `calculate_pnl(trade, 0.0)` path. Total: **+$29.09** of real
`bond_scanner` wins are currently mislabeled as `result="loss"`, understating
its win rate (relevant to the "Auto-kill at <30% win rate" governance rule —
this strategy is currently on live-trading probation).

### `_settle_btc_5min_trade`'s `expired_unresolved` branch is doubly wrong

This branch additionally sets `trade.result = "expired_unresolved"` (not
`"loss"`). `botstate_ledger.py::is_push` treats `result == "expired_unresolved"`
as a push (full cost-basis credited back, `pnl` ignored for bankroll
purposes). Simply swapping in `total_loss_settlement_value` here — without
also changing `result` — would make `pnl` a real negative "total loss" while
the bankroll still credits back the full cost basis as a push: a *new*
pnl/bankroll mismatch. No `bond_scanner` trades have hit this branch yet
(zero rows with `settlement_source="btc_5min_unresolved"`), but
`crypto_oracle`/`cex_pm_leadlag` BTC 5-min trades could.

### Latent crash: naive/aware datetime comparison

`_settle_btc_5min_trade`'s final branch compares
`now < trade.timestamp + timedelta(hours=24)` where `now` is tz-aware
(`datetime.now(timezone.utc)`, passed in from `settle_pending_trades`) and
`trade.timestamp` is naive (per `c2e92f5e`, all DB `DateTime` columns are
naive UTC). This raises `TypeError: can't compare offset-naive and
offset-aware datetimes` the first time any `btc-updown-5m-*` trade goes
unresolved for 24h — which would propagate out of
`_settle_btc_5min_trade` → `settle_pending_trades`'s per-trade loop,
aborting settlement for the **entire batch** of pending trades in that
cycle (all strategies, not just BTC 5-min), violating "Settlement is Sacred
— stale positions block orders."

## Decision

1. Apply `total_loss_settlement_value(trade.direction)` (from ADR-016) to
   all four deferred branches, exactly as ADR-016 did for
   `force_closed_unresolved`:
   - `closed_unresolved` (`settlement.py::settle_pending_trades`, grace
     exhausted)
   - `expired_unresolved` (`settlement.py::settle_pending_trades`,
     `market_end_date` passed)
   - `stale_expired` (`settlement.py::settle_pending_trades`, stale +
     on-chain-confirmed-gone)
   - `btc_5min_unresolved` (`settlement.py::_settle_btc_5min_trade`, 24h
     timeout)

2. For `_settle_btc_5min_trade`'s timeout branch, also change
   `trade.result` from `"expired_unresolved"` to `"loss"`, matching the
   other three branches above (all already use `result="loss"` +
   `total_loss_settlement_value`-derived `pnl`). This keeps `result`,
   `pnl`, and `is_push`/`is_loss` bankroll treatment mutually consistent:
   `result="loss"` → `is_loss=True` → bankroll uses the real negative
   `pnl`, which is now `-cost_basis`.

3. Fix the naive/aware `datetime` comparison in
   `_settle_btc_5min_trade` by normalizing `trade.timestamp` to tz-aware UTC
   before comparing with `now`, matching the existing pattern at
   `settlement.py:589-590` (`market_end`) and `:634-635` (`ts`).

## Alternatives Considered

Same as ADR-016 Alternative 1 (rejected: changing `result` away from
`"loss"` to dodge the pnl-sign mismatch would retroactively improve
`bond_scanner`'s win rate — the opposite of "make numbers accurate, not
better-looking").

## Consequences

- New `closed_unresolved`/`expired_unresolved`/`stale_expired`/
  `btc_5min_unresolved` settlements record `pnl = calculate_pnl(trade,
  total_loss_settlement_value(trade.direction))` — always `<= 0`, consistent
  with `result="loss"`, for both YES/UP and NO/DOWN positions.
- `_settle_btc_5min_trade`'s 24h-timeout branch now records `result="loss"`
  (previously `"expired_unresolved"`), so `botstate_ledger.is_push` no longer
  treats it as a push — the bankroll absorbs the assumed total loss,
  consistent with the recorded `pnl`.
- The 11 existing `bond_scanner` rows (+$29.09 mislabeled as losses) are
  **not backfilled** — per ADR-016 Alternative 3 and CLAUDE.md's "Trade
  records are append-only", historical correction is a data-backfill
  decision deferred to a follow-up, reviewed separately from this
  settlement-logic fix.
- `_settle_btc_5min_trade` no longer crashes on its 24h-timeout path,
  removing a settlement-batch-wide failure mode for BTC 5-min strategies.
- `unified_arb`'s and `bond_scanner`'s `force_closed_unresolved` rows
  (ADR-016) are unaffected by this ADR — different branches, already fixed.
