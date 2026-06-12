# ADR-015: Apply LONGSHOT_NO_BIAS_WEIGHT Before the Confidence Floor

**Status:** Accepted
**Date:** 2026-06-12

## Context

`RiskManager.validate_trade()` rejects any trade where `confidence < min_confidence`
(`PAPER_AUTO_APPROVE_MIN_CONFIDENCE` / `AUTO_APPROVE_MIN_CONFIDENCE`, 0.50 by
default). This floor is a sanity check for directional/favorite strategies:
"don't bet on an outcome we think is more likely to lose than win."

`longshot_bias` (re-enabled 2026-06-12 after the candidate-direction fix in
`docs/APEX_PAPER_TRIAL_STATUS_2026-06-10.md`, Bug K) buys the **NO** token on
markets where `no_price < 0.25` and the favorite (`yes_price`) is priced at
`>= 0.75`. By construction, `confidence = true_win_prob = 1 - yes_price *
bias_ratio` is in the **0.41-0.50** range for every real candidate — the bet
is a longshot. Its positive EV comes from favorable payout odds (NO costs
5-12c but wins often enough to be +EV), not from `P(NO wins) > 0.5`.

The risk manager already has a mechanism for exactly this case:
`LONGSHOT_NO_BIAS_WEIGHT` (0.10 by default, introduced in commit `a23a8b31`,
"NO-bias weighting") boosts `confidence` for `direction == "NO"` trades by
`confidence * (1 + bias_weight)`. However, since that commit it has been
applied **after** the `confidence < min_confidence` rejection — every
genuine longshot NO trade was rejected before the adjustment could run,
making `LONGSHOT_NO_BIAS_WEIGHT` dead code for its intended purpose.

Live verification after the Bug K fix confirmed this: the first post-restart
cycle produced 10 `longshot_bias` decisions
(`confidence` 0.41-0.48, `edge` 65-99%, `EV` 35-41%, all passing the
strategy's own `min_edge=0.15` / `min_model_prob=0.75` guards and the risk
manager's `MIN_TRADE_EV` / `check_edge` filters), and **all 10 were rejected**
by `_preflight_checks` with `"Risk rejected ...: confidence 0.XX < min
threshold 0.50"`. Net effect: `longshot_bias` produced zero trades in paper
mode, so its profitability could not be validated live — directly blocking
the "profitable both live & paper, not only theoretically" goal.

## Decision

Move the `LONGSHOT_NO_BIAS_WEIGHT` adjustment block in
`backend/core/risk/risk_manager.py::validate_trade()` to run **before** the
`confidence < min_confidence` check, so the adjusted confidence is what the
floor evaluates. No threshold values, edge filters, or other risk checks are
relaxed — `MIN_TRADE_EV`, `check_edge`, drawdown/exposure/concentration
limits, and the category edge filter are unchanged and continue to run.

With the default `LONGSHOT_NO_BIAS_WEIGHT=0.10`, a NO bet's confidence is
boosted by 10% before the floor check (`confidence >= 0.4546` now passes
the 0.50 floor instead of requiring `confidence >= 0.50` outright). YES bets
continue to be *penalized* (`confidence * (1 - bias_weight * 0.5)`), which
can now correctly cause a borderline YES bet to fail the floor — this is the
designed behavior, simply applied where it can take effect.

## Alternatives Considered

1. **Lower `PAPER_AUTO_APPROVE_MIN_CONFIDENCE` globally.** Rejected — affects
   every strategy and every direction, a much larger blast radius than fixing
   one strategy's bias adjustment.
2. **Have `longshot_bias` report a different `confidence` value** (e.g. the
   favorite's market-implied probability, `yes_price`, instead of
   `P(NO wins)`). Rejected — would make `confidence` mean "P(our bet wins)"
   for every other strategy but "P(the *other* side wins)" for this one,
   corrupting the field's meaning for calibration, dashboards, and any future
   strategy that also bets genuine longshots.
3. **Increase `LONGSHOT_NO_BIAS_WEIGHT` beyond 0.10** so that *all* current
   candidates (down to `confidence=0.41`) clear the floor. Deferred — would
   require `bias_weight >= 0.22`, a larger behavioral change than fixing the
   ordering bug alone. The ordering fix already lets ~30% of candidates
   through per cycle (enough to start building a live paper track record);
   revisit the weight value only if that track record shows the remaining
   candidates (`confidence` 0.41-0.49) are also profitable.

## Consequences

- `longshot_bias` can now place paper trades again; its win rate / PnL can be
  measured against real settlement outcomes instead of being permanently
  gated at zero trades.
- Any other strategy that bets `direction="NO"` with `confidence` between
  `min_confidence / (1 + LONGSHOT_NO_BIAS_WEIGHT)` and `min_confidence` will
  also now pass where it previously didn't. This is the intended effect of
  the existing per-risk-profile `longshot_no_bias_weight` setting
  (0.05-0.20 across profiles) and was already configured — it simply now
  works.
- `direction="YES"` trades with `confidence` just above 0.50 can now be
  rejected by the floor after the penalty is applied
  (`confidence * (1 - bias_weight * 0.5)`), where previously the penalty was
  computed but discarded. This is the designed symmetric behavior.
