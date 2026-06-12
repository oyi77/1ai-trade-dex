# ADR-017: APEX Early-Exit Settlement (Profit Target / Stop Loss / Time Decay)

**Status:** Accepted
**Date:** 2026-06-13

## Context

`apex_strategy.py`'s `run_cycle` Phase 1 calls `_check_exits`, which uses
`ExitManager.check_all_positions` to evaluate every open `apex` position
against `profit_target_pct` (2.5%), `stop_loss_pct` (4%), `max_hold_seconds`
(7200s), and edge decay. When a signal fired, Phase 1 only appended:

```python
{"market_ticker": sig.market_id, "direction": "SELL", "decision": "SELL",
 "exit_reason": sig.reason.value, "urgency": sig.urgency}
```

This dict has no `token_id`, so it is silently dropped by both
`scheduling_strategies.py`'s buy-decision filter (`decision in ("BUY",
"QUOTE")`) and the shadow-runner loop (`decision.get("token_id")`). **No
position was ever closed by this code path.** Combined with
`StrategyExecutor` having no `decision.get("side") == "SELL"` handling
anywhere (confirmed via grep — the only `"SELL"`-producing path,
`position_monitor.py`'s `sell_signal_monitor_job`, opens a new *opposite*
position rather than closing the original), APEX positions could only ever
be resolved by Gamma market settlement (binary 0/1) at market close — never
by APEX's own risk management. Losing positions ran to full settlement
instead of being cut at -4%, directly working against "profitable both live
& paper, not only theoretically."

Separately, `ExitManager.check_position`'s `pnl_pct` was computed as:

```python
if direction in ("yes", "up"):
    pnl_pct = (current_price - entry_price) / entry_price
else:
    pnl_pct = (entry_price - current_price) / entry_price
```

All three APEX edge scanners (`resolution_timing`, `order_book_stale`,
`liquidity_gap`) record `entry_price` as the price of the **held token**
(`trade.token_id`) at entry, and `_get_current_price` fetches the mid price
of the same `trade.token_id`. Both prices are already in "held-token" terms,
so flipping the sign for `no`/`down` positions inverted `pnl_pct` for any
non-"yes" position — a losing NO position would read as a *gain* and vice
versa, corrupting both the profit-target and stop-loss checks.

## Decision

1. **`exit_manager.py`**: remove the `direction` branch. `pnl_pct =
   (current_price - entry_price) / entry_price` unconditionally — both
   prices are in held-token terms for every APEX scanner, making the
   calculation direction-independent by construction.

2. **`settlement_helpers.py`**: add `calculate_exit_pnl(trade, exit_price) ->
   (pnl, fee)`. Unlike `calculate_pnl` (binary settlement, `settlement_value
   ∈ {0.0, 1.0}`), this is a **partial** realization at a continuous
   `exit_price` in the same held-token terms as `entry_price`:

   ```
   pnl = shares * (exit_price - entry_price) - entry_fee - exit_fee
   ```

   `entry_fee` reuses `trade.fee` if already recorded (else recomputed the
   same way `calculate_pnl` does). `exit_fee` is a **new** taker fee on the
   exit leg — an early exit requires a real CLOB sell order, unlike binary
   redemption at settlement which has no fee. Both prices use `fill_price`/
   `filled_size` when present, mirroring `calculate_pnl`'s field precedence.

3. **`apex_strategy.py`**:
   - `_check_exits` now applies the ADR-016 `or_(Trade.settled.is_(False),
     Trade.pnl.is_(None))` filter (previously only `settled.is_(False)`),
     so positions stuck in the ADR-016 limbo window (`settled=True,
     pnl=NULL`, awaiting Gamma resolution) are still eligible for an APEX
     early exit rather than waiting up to 5 days for
     `force_closed_unresolved`.
   - New `_close_position(sig, ctx)`: looks up the `Trade` by
     `sig.trade_id`, guards against re-closing an already-fully-settled
     trade (`settled and pnl is not None`), computes
     `calculate_exit_pnl(trade, sig.exit_price)`, and sets `trade.settled =
     True`, `trade.pnl`, `trade.result` (`"win"`/`"loss"`/`"push"` —
     standard values for win-rate/health-check compatibility, not a new
     enum), `trade.settlement_time = utcnow()`, `trade.settlement_source =
     f"early_exit_{sig.reason.value}"` (e.g. `early_exit_profit_target`,
     `early_exit_stop_loss`, `early_exit_time_decay`).
   - New `_place_exit_order(trade, exit_price, ctx)`: **live mode only**.
     Gated by `StrategyGate.can_execute_live("apex", db)` — apex is
     currently PAPER-only, so this path is dormant until promoted through
     the strategy gating pipeline. Places a CLOB SELL at `exit_price *
     (1 - 2%)` (same marketable-premium pattern as `bond_scanner.py`'s BUY
     entries, applied below mid to guarantee a fill) for `shares =
     filled_size or size`. On rejection or any error, returns `None` and
     `_close_position` leaves the trade open for retry next cycle — no
     partial state is written.
   - Phase 1 now calls `_close_position` for each exit signal and, on
     success, includes `pnl`/`result` in the emitted decision dict (still
     not consumed downstream — the close already happened via direct
     `ctx.db` mutation, the same established pattern as `_log_decision` and
     `_get_existing_positions`).

4. **`paper_pnl_audit.py`**: `_settlement_value_for_trade` returns `None` for
   `settlement_source` starting with `early_exit_` — these are partial
   realizations, not binary settlements, so `calculate_pnl(trade,
   settlement_value)` would compute a different (full-binary) number and
   falsely flag every early exit as a pnl mismatch.

## Alternatives Considered

1. **Fix `sell_signal_monitor_job` / wire `decision.get("side") == "SELL"`
   into `StrategyExecutor` as a generic close path.** Rejected for this fix
   — `sell_signal_monitor_job`'s stop-loss threshold
   (`STOP_LOSS_DROP_PP=0.15`, a 15-percentage-point probability drop) is far
   looser than APEX's `stop_loss_pct=4%`; APEX's confirmed actual losses
   were -16% to -50% `pnl_pct` (0.02-0.05 probability points), well under
   0.15, so this path would not have caught them even if it correctly closed
   positions (it doesn't — it opens a hedge). A generic SELL-as-close path
   is a larger cross-cutting change affecting every strategy and is deferred.

2. **Route the live exit through `StrategyExecutor`'s existing
   `_execute_decision_live_clob`.** Rejected — that path is BUY-shaped
   (sizes in USD, `_record_trade` creates a *new* Trade row). Closing an
   existing Trade in place via `ctx.db` directly (as `_get_existing_positions`
   and `_log_decision` already do) is simpler and avoids a new Trade row
   representing the same economic position twice.

3. **Credit `BotState.paper_bankroll` on close.** Rejected for consistency —
   no existing settlement path (Gamma resolution, `force_closed_unresolved`,
   `closed_unresolved`) credits `paper_bankroll` back on close; bankroll
   accounting relies on the separate auto-topup mechanism in
   `settlement.py`. Changing this would be a separate, broader bankroll-
   accounting change.

## Consequences

- APEX paper positions can now actually hit profit-target (+2.5%) and
  stop-loss (-4%) exits instead of running to full Gamma settlement —
  expected to reduce loss magnitude on the -16% to -50% trades identified in
  `docs/APEX_PAPER_TRIAL_STATUS_2026-06-10.md`.
- `Trade.result` for early-exited trades is `"win"`/`"loss"`/`"push"` based
  on the *partial* pnl sign, which may differ from what the market eventually
  settles to — this is intentional (the position was closed before
  settlement, so the realized outcome is the early-exit outcome).
- `settlement_source` gains new values (`early_exit_profit_target`,
  `early_exit_stop_loss`, `early_exit_time_decay`, `early_exit_edge_decay`)
  alongside existing `gamma_resolution`, `force_closed_unresolved`,
  `closed_unresolved`.
- Live exits remain gated by `StrategyGate.can_execute_live` and are
  untested in this change (apex is paper-only; CLAUDE.md prohibits live
  trading tests without `SHADOW_MODE=true`). A blocked/failed live exit
  leaves the Trade open for retry next cycle.
