"""RiskManager validation mixin — validate_trade pipeline."""

from __future__ import annotations

import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, or_

from loguru import logger

from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import Trade, BotState, for_update
from backend.monitoring.hft_metrics import record_signal, db_query_duration
from backend.monitoring.metrics import increment_risk_rejection
from backend.core.risk.correlation_monitor import CorrelationMonitor

from backend.core.risk._risk_manager_types import (
    RiskDecision,
    EdgeFilterError,
    DrawdownStatus,
    IMMUTABLE_SAFETY_RULES,
    _not_backfill_settlement_source,
)



class RiskManagerValidationMixin:
    """Mixin — method implementations live on RiskManager."""

    def validate_trade(
        self,
        size: float,
        current_exposure: float,
        bankroll: float,
        confidence: float,
        market_ticker: Optional[str] = None,
        slippage: Optional[float] = None,
        db=None,
        mode: Optional[str] = None,
        strategy_name: Optional[str] = None,
        direction: Optional[str] = None,
        category: Optional[str] = None,
        market_price: Optional[float] = None,
        signal_win_rate: Optional[float] = None,
    ) -> RiskDecision:
        effective_mode = mode or self.s.TRADING_MODE
        original_available_cash = bankroll
        if effective_mode == "live" and db is not None:
            try:
                from backend.models.database import PlatformBalance
                balances = db.query(PlatformBalance).filter_by(mode="live").all()
                total_equity = sum(float(b.total_equity or 0.0) for b in balances)
                if total_equity > 0:
                    bankroll = total_equity
                    logger.debug(f"[risk_manager] Live mode: using total live equity as bankroll base: ${bankroll:.2f}")
            except Exception as e:
                logger.warning(f"[risk_manager] Failed to fetch total live equity for bankroll base: {e}")

        signal_win_rate, calibration_stats, longshot_bias_stats = self._validate_trade_calibration(
            db, market_price, signal_win_rate
        )

        if (
            db is not None
            and market_price is not None
            and direction
            and direction.upper() in ("YES", "UP")
            and market_price < 0.30
        ):
            try:
                _, longshot_bias_stats = self._get_or_update_calibration_and_bias(db)
                if longshot_bias_stats and "bias" in longshot_bias_stats:
                    bias = longshot_bias_stats["bias"]
                    if bias < 0.8:
                        logger.info(
                            "[risk_manager] Longshot YES trade blocked: overall bias={:.4f} < 0.8 (market={}, price={:.3f})",
                            bias,
                            market_ticker or "unknown",
                            market_price,
                        )
                        record_signal(
                            strategy=strategy_name or "unknown",
                            signal_type="blocked_longshot_yes_bias",
                        )
                        increment_risk_rejection(
                            strategy=strategy_name or "unknown",
                            reason="longshot_yes_bias",
                        )
                        return RiskDecision(
                            False,
                            f"longshot YES bet blocked: overall bias ratio {bias:.4f} is critically low (< 0.8)",
                            0.0,
                        )
                    else:
                        original_size = size
                        size = size * bias
                        logger.info(
                            "[risk_manager] Longshot YES bet size dynamically scaled: ${:.2f} -> ${:.2f} (bias={:.4f})",
                            original_size,
                            size,
                            bias,
                        )
            except Exception as e:
                logger.error(f"[RiskManager] Failed to apply longshot bias signal: {e}")

        from backend.strategies.registry import STRATEGY_REGISTRY

        params = None
        if strategy_name in STRATEGY_REGISTRY:
            _dp = getattr(STRATEGY_REGISTRY[strategy_name], "default_params", {})
            # default_params may be a dataclass Field sentinel — be strict: only accept real dicts
            if isinstance(_dp, dict):
                params = dict(_dp)
            elif hasattr(_dp, "items") and callable(getattr(_dp, "items", None)):
                try:
                    params = dict(_dp.items())
                except Exception:
                    params = None
            else:
                params = None
        if params and params.get("_force_disabled", False):
            return RiskDecision(False, "strategy explicitly disabled", 0.0)

        if market_price is not None and direction:
            longshot_yes_reject = getattr(self.s, "LONGSHOT_YES_REJECT_PRICE", 0.30)
            if (
                self._longshot_bias_cache is None
                and direction.upper() == "YES"
                and market_price < longshot_yes_reject
            ):
                record_signal(
                    strategy=strategy_name or "unknown",
                    signal_type="rejected_longshot_yes",
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="longshot_yes"
                )
                logger.info(
                    "[risk_manager] Longshot YES rejection: market={} price={:.3f} < {:.3f} (negative EV)",
                    market_ticker or "unknown",
                    market_price,
                    longshot_yes_reject,
                )
                return RiskDecision(
                    False,
                    f"longshot YES rejected: price={market_price:.3f} < {longshot_yes_reject:.3f} (negative EV)",
                    0.0,
                )

        if category and market_price is not None and signal_win_rate is not None:
            cat_min_edge = getattr(self.s, "CATEGORY_MIN_EDGE", {})
            min_edge_for_cat = cat_min_edge.get(category.lower(), 0.03)
            edge = signal_win_rate - market_price
            if edge < min_edge_for_cat:
                record_signal(
                    strategy=strategy_name or "unknown",
                    signal_type="rejected_category_edge",
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="category_edge"
                )
                logger.info(
                    "[risk_manager] Category edge rejection: cat={} edge={:.4f} < min={:.4f} (market={} price={:.3f} swr={:.3f})",
                    category,
                    edge,
                    min_edge_for_cat,
                    market_ticker or "unknown",
                    market_price,
                    signal_win_rate,
                )
                return RiskDecision(
                    False,
                    f"category '{category}' edge {edge:.4f} < min {min_edge_for_cat:.4f}",
                    0.0,
                )

        if market_price is not None and signal_win_rate is not None and size > 0:
            min_trade_ev = getattr(self.s, "MIN_TRADE_EV", 0.10)
            edge = abs(signal_win_rate - market_price)
            ev = edge * size
            if ev < min_trade_ev:
                record_signal(
                    strategy=strategy_name or "unknown", signal_type="rejected_min_ev"
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="min_ev"
                )
                logger.info(
                    "[risk_manager] Min EV rejection: ev=${:.4f} < min=${:.4f} (edge={:.4f} size=${:.2f})",
                    ev,
                    min_trade_ev,
                    edge,
                    size,
                )
                return RiskDecision(
                    False,
                    f"trade EV ${ev:.4f} < min ${min_trade_ev:.4f}",
                    0.0,
                )

        if market_price is not None and signal_win_rate is not None:
            try:
                self.check_edge(
                    market_price=market_price,
                    signal_win_rate=signal_win_rate,
                    market_id=market_ticker or "unknown",
                    db=db,
                )
            except EdgeFilterError as e:
                record_signal(
                    strategy=strategy_name or "unknown", signal_type="rejected_edge"
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="edge"
                )
                logger.info(
                    "[risk_manager] edge filter rejection: market={} price={:.3f} swr={:.3f} edge_pp={:.2f}",
                    e.market_id,
                    e.market_price,
                    e.signal_win_rate,
                    e.edge_pp,
                )
                return RiskDecision(False, e.message, 0.0)

        # NO-bias adjustment must run BEFORE the confidence floor below — it
        # exists specifically to correct raw P(win) for asymmetric longshot
        # bets, where P(win) < 0.5 is expected by design. Applying it after
        # the floor (the original ordering) made LONGSHOT_NO_BIAS_WEIGHT dead
        # code: every genuine longshot NO bet was rejected before the
        # adjustment could run. See adr-015-longshot-no-bias-confidence-ordering.md.
        bias_weight = getattr(self.s, "LONGSHOT_NO_BIAS_WEIGHT", 0.0)
        if bias_weight > 0 and direction:
            original_conf = confidence
            if direction.upper() == "NO":
                confidence = min(1.0, confidence * (1 + bias_weight))
            elif direction.upper() == "YES":
                confidence = confidence * (1 - bias_weight * 0.5)
            if confidence != original_conf:
                logger.info(
                    "[risk_manager] Applied NO-bias: {} -> {:.2f} -> {:.2f}",
                    direction,
                    original_conf,
                    confidence,
                )

        min_confidence = self._get_confidence_threshold(effective_mode, strategy_name)
        if confidence < min_confidence:
            record_signal(
                strategy=strategy_name or "unknown", signal_type="rejected_confidence"
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="confidence"
            )
            return RiskDecision(
                False,
                f"confidence {confidence:.2f} < min threshold {min_confidence:.2f}",
                0.0,
            )

        cat_enabled = getattr(self.s, "CATEGORY_CONFIDENCE_ENABLED", False)
        if cat_enabled and category:
            cat_multipliers = getattr(self.s, "CATEGORY_CONFIDENCE_MULTIPLIER", {})
            multiplier = cat_multipliers.get(category.lower(), 1.0)
            if multiplier != 1.0:
                pre_cat = confidence
                confidence = min(1.0, confidence * multiplier)
                logger.info(
                    "[risk_manager] Applied category multiplier: {} {:.2f} x{:.2f} -> {:.2f}",
                    category,
                    pre_cat,
                    multiplier,
                    confidence,
                )

        rejection = self._validate_trade_daily_loss_breaker(effective_mode, db, strategy_name)
        if rejection:
            return RiskDecision(False, rejection, 0.0)

        rejection = self._validate_trade_drawdown_breaker(bankroll, db, effective_mode, strategy_name)
        if rejection:
            return RiskDecision(False, rejection, 0.0)

        rejection = self._validate_trade_category_breaker(category, db, effective_mode, strategy_name)
        if rejection:
            return RiskDecision(False, rejection, 0.0)

        if strategy_name and db is not None:
            max_strat_dd = float(
                getattr(self.s, "MAX_STRATEGY_DRAWDOWN_PCT", 0.15) or 0.15
            )
            strat_allocation = self._get_strategy_allocation(
                strategy_name, bankroll, db, effective_mode
            )
            strat_dd = self._check_strategy_drawdown(strategy_name, db, effective_mode)
            if strat_dd is None:
                record_signal(
                    strategy=strategy_name,
                    signal_type="rejected_strategy_drawdown_db_error",
                )
                increment_risk_rejection(
                    strategy=strategy_name, reason="strategy_drawdown_db_error"
                )
                logger.error(
                    "[risk_manager] DB error checking strategy drawdown for {}; aborting trade for capital safety.",
                    strategy_name,
                )
                return RiskDecision(
                    False,
                    f"DB error checking strategy drawdown for {strategy_name}",
                    0.0,
                )
            elif (
                strat_allocation > 0
                and strat_dd < 0
                and abs(strat_dd) > strat_allocation * max_strat_dd
            ):
                record_signal(
                    strategy=strategy_name, signal_type="rejected_strategy_drawdown"
                )
                increment_risk_rejection(
                    strategy=strategy_name, reason="strategy_drawdown"
                )
                logger.info(
                    "[risk_manager] Per-strategy drawdown: {} loss=${:.2f} > {:.0%} of allocation=${:.2f}",
                    strategy_name,
                    abs(strat_dd),
                    max_strat_dd,
                    strat_allocation,
                )
                return RiskDecision(
                    False,
                    f"strategy {strategy_name} drawdown ${abs(strat_dd):.2f} > {max_strat_dd:.0%} of allocation",
                    0.0,
                )

        if market_ticker and db is not None:
            conc_reason = self.check_concentration(
                market_ticker, size, bankroll, db, effective_mode
            )
            if conc_reason:
                record_signal(
                    strategy=strategy_name or "unknown",
                    signal_type="rejected_concentration",
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="concentration"
                )
                return RiskDecision(False, conc_reason, 0.0)

        if market_ticker and self._has_unsettled_trade(
            market_ticker, db=db, mode=effective_mode, direction=direction,
            strategy_name=strategy_name,
        ):
            record_signal(
                strategy=strategy_name or "unknown", signal_type="rejected_unsettled"
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="unsettled"
            )
            return RiskDecision(
                False, f"unsettled trade exists for {market_ticker}", 0.0
            )

        if market_ticker and direction:
            conflicting_side = self.check_side_lock(
                market_ticker=market_ticker,
                direction=direction,
                db=db,
                mode=effective_mode,
            )
            if conflicting_side is not None:
                record_signal(
                    strategy=strategy_name or "unknown",
                    signal_type="rejected_sidelock",
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="sidelock"
                )
                return RiskDecision(
                    False,
                    f"side-lock: opposing {conflicting_side} position open on {market_ticker}",
                    0.0,
                )

        # Cross-market correlation check + concentration limits
        adjusted, max_capacity, rejection = self._validate_trade_concentration(
            size, bankroll, current_exposure, market_ticker, db, effective_mode, strategy_name
        )
        if rejection is not None:
            return RiskDecision(False, rejection, 0.0)

        if slippage is not None and slippage > self.s.SLIPPAGE_TOLERANCE:
            record_signal(
                strategy=strategy_name or "unknown", signal_type="rejected_slippage"
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="slippage"
            )
            return RiskDecision(False, f"slippage {slippage:.4f} > tolerance", 0.0)

        # Per-strategy allocation
        adjusted, max_capacity, rejection = self._validate_trade_strategy_allocation(
            strategy_name, adjusted, max_capacity, bankroll, db, effective_mode
        )
        if rejection is not None:
            return RiskDecision(False, rejection, 0.0)

        if (
            bool(getattr(self.s, "VOLATILITY_SIZE_SCALE", True))
            and market_price is not None
        ):
            vol_factor = 4.0 * market_price * (1.0 - market_price)
            vol_factor = max(0.25, min(1.0, vol_factor))
            if vol_factor < 1.0:
                pre_vol_size = adjusted
                adjusted = adjusted * vol_factor
                max_capacity = min(max_capacity, adjusted)
                logger.info(
                    "[risk_manager] Volatility scale: price={:.3f} factor={:.2f} size ${:.2f} -> ${:.2f}",
                    market_price,
                    vol_factor,
                    pre_vol_size,
                    adjusted,
                )
        if effective_mode == "live":
            adjusted = min(adjusted, original_available_cash)

        min_order_usdc = (
            self.s.PAPER_MIN_ORDER_USDC
            if effective_mode == "paper"
            else self.s.MIN_ORDER_USDC
        )
        if 0 < adjusted < min_order_usdc:
            if max_capacity >= min_order_usdc:
                adjusted = min_order_usdc
                logger.info(
                    "[risk_manager] Raised %s trade size to venue minimum: $%.2f -> $%.2f",
                    effective_mode,
                    adjusted,
                    adjusted,
                )
            elif (
                original_available_cash <= getattr(self.s, "MAX_TRADE_SIZE", float("inf"))
                and original_available_cash > 0
                and min_order_usdc <= original_available_cash * 0.95
            ):
                adjusted = min_order_usdc
                logger.info(
                    "[risk_manager] Bumped %s trade to CLOB minimum despite cap: "
                    "$%.2f -> $%.2f (original_available_cash=%.2f)",
                    effective_mode,
                    min_order_usdc - (adjusted - min_order_usdc),
                    adjusted,
                    original_available_cash,
                )
            else:
                record_signal(
                    strategy=strategy_name or "unknown",
                    signal_type="rejected_min_order",
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="min_order"
                )
                return RiskDecision(
                    False,
                    f"size ${adjusted:.2f} below minimum order ${min_order_usdc:.2f}",
                    0.0,
                )

        # ── Per-strategy drawdown enforcement ──
        if db is not None and strategy_name and strategy_name != "unknown":
            try:
                from backend.models.database import Trade
                from sqlalchemy import func

                max_dd_pct = getattr(self.s, "MAX_STRATEGY_DRAWDOWN_PCT", 0.30)
                # Skip if set to 100% (disabled)
                if max_dd_pct < 1.0:
                    strategy_pnl = (
                        db.query(func.coalesce(func.sum(Trade.pnl), 0.0))
                        .filter(
                            Trade.strategy == strategy_name,
                            Trade.trading_mode == effective_mode,
                            Trade.settled.is_(True),
                        )
                        .scalar()
                    )
                    if bankroll > 0:
                        dd_pct = abs(min(0.0, float(strategy_pnl))) / bankroll
                        if dd_pct > max_dd_pct:
                            logger.warning(
                                "[risk_manager] Per-strategy DD BLOCKED: {} dd={:.1%} > max={:.1%}",
                                strategy_name, dd_pct, max_dd_pct,
                            )
                            return RiskDecision(
                                False,
                                f"strategy drawdown {dd_pct:.1%} > max {max_dd_pct:.0%}",
                                0.0,
                            )
            except Exception as e:
                logger.debug(f"[risk_manager] Per-strategy DD check failed (non-fatal): {e}")

        return RiskDecision(True, "ok", adjusted)

    def _validate_trade_daily_loss_breaker(
        self, effective_mode: str, db, strategy_name: Optional[str]
    ) -> Optional[str]:
        """Check daily loss circuit breaker. Returns rejection reason or None."""
        if not self._breaker_enabled_for_mode("daily_loss", effective_mode):
            logger.debug(
                "[risk_manager] Daily loss breaker disabled for mode=%s — skipping",
                effective_mode,
            )
            return None
        if self._daily_loss_exceeded(db=db, mode=effective_mode):
            record_signal(
                strategy=strategy_name or "unknown", signal_type="rejected_daily_loss"
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="daily_loss"
            )
            return "daily loss limit hit"
        return None

    def _validate_trade_drawdown_breaker(
        self, bankroll: float, db, effective_mode: str, strategy_name: Optional[str]
    ) -> Optional[str]:
        """Check drawdown breaker. Returns rejection reason or None."""
        if not self._breaker_enabled_for_mode("drawdown", effective_mode):
            logger.debug(
                "[risk_manager] Drawdown breaker disabled for mode=%s — skipping",
                effective_mode,
            )
            return None
        drawdown = self.check_drawdown(bankroll, db=db, mode=effective_mode)
        if drawdown.is_breached:
            record_signal(
                strategy=strategy_name or "unknown", signal_type="rejected_drawdown"
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="drawdown"
            )
            return f"drawdown breaker: {drawdown.breach_reason}"
        return None

    def _validate_trade_category_breaker(
        self, category: Optional[str], db, effective_mode: str, strategy_name: Optional[str]
    ) -> Optional[str]:
        """Check category circuit breaker. Returns rejection reason or None."""
        if not (category and db is not None):
            return None
        cat_cooldown = self._check_category_circuit_breaker(
            category, db, effective_mode
        )
        if cat_cooldown:
            record_signal(
                strategy=strategy_name or "unknown",
                signal_type="rejected_category_breaker",
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="category_breaker"
            )
            return cat_cooldown
        return None

    def _validate_trade_calibration(self, db, market_price, signal_win_rate):
        """Calibration adjustment logic (price bucket calibration, signal_win_rate adjustment)."""
        calibration_stats = {}
        longshot_bias_stats = {}
        if db is not None and market_price is not None and signal_win_rate is not None:
            try:
                calibration_stats, longshot_bias_stats = self._get_or_update_calibration_and_bias(db)
                bucket_start = int(market_price * 100) - (int(market_price * 100) % 5)
                if bucket_start in calibration_stats:
                    bucket = calibration_stats[bucket_start]
                    if bucket.get("confidence", 0.0) >= 0.3:
                        adjustment = bucket["error"] * bucket["confidence"]
                        adjustment = max(-0.05, min(0.05, adjustment))
                        pre_adj = signal_win_rate
                        # CALIBRATION GUARD: never adjust swr below market_price,
                        # otherwise edge_pp = (swr - price) * 100 turns negative
                        # and the edge filter rejects EVERY trade — permanent deadlock.
                        max_down = max(0.0, pre_adj - market_price - 0.005)
                        adjustment = max(adjustment, -max_down)
                        signal_win_rate = max(
                            0.01, min(0.995, pre_adj + adjustment)
                        )
                        logger.info(
                            "[risk_manager] Realized calibration adjustment for bucket {}c: {:.2f} -> {:.2f} (error={:.2%}, conf={:.2f})",
                            bucket_start,
                            pre_adj,
                            signal_win_rate,
                            bucket["error"],
                            bucket["confidence"],
                        )
            except Exception as e:
                logger.error(
                    f"[RiskManager] Failed to apply calibration adjustment: {e}"
                )
        return signal_win_rate, calibration_stats, longshot_bias_stats

    def _validate_trade_concentration(
        self, size, bankroll, current_exposure, market_ticker, db, effective_mode, strategy_name
    ):
        """Cross-market correlation check + concentration limits. Returns (adjusted_size, max_capacity, rejection_reason)."""
        # Cross-market correlation check — block if clustered exposure > 30% of bankroll
        if market_ticker and db is not None:
            corr_result = self._correlation_monitor.check_correlation(
                bankroll=bankroll,
                market_ticker=market_ticker,
                trade_size=size,
                event_slug=None,  # market_ticker is a string; event_slug must be passed separately
                db=db,
                mode=effective_mode,
            )
            if not corr_result.allowed:
                record_signal(
                    strategy=strategy_name or "unknown",
                    signal_type="rejected_correlation",
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="correlation"
                )
                return 0.0, 0.0, corr_result.reason

        # Live bankroll = PM portfolio value (includes locked positions);
        # available cash = portfolio minus open exposure.
        if effective_mode == "live":
            available_cash = max(0.0, bankroll - current_exposure)
            max_position = available_cash * self.s.MAX_POSITION_FRACTION
        else:
            max_position = bankroll * self.s.MAX_POSITION_FRACTION
        max_capacity = max_position
        adjusted = min(size, max_position)

        # Global max trade size ceiling (immutable safety rule)
        adjusted = min(adjusted, self.s.MAX_TRADE_SIZE)
        max_capacity = min(max_capacity, self.s.MAX_TRADE_SIZE)

        # Paper/testnet bankroll is available cash because entry execution
        # deducts stake immediately; total exposure limits must use equity
        # (cash + already-open stake), otherwise existing positions shrink the
        # denominator and can permanently block new trades. Live bankroll is
        # PM portfolio value, which already includes locked positions.
        exposure_base = (
            bankroll if effective_mode == "live" else bankroll + current_exposure
        )
        # Use immutable safety rule for max total exposure
        max_exposure = exposure_base * self._safety_rules["max_total_exposure"]
        exposure_room = max(0.0, max_exposure - current_exposure)
        max_capacity = min(max_capacity, exposure_room)
        if current_exposure + adjusted > max_exposure:
            adjusted = exposure_room
            if adjusted <= 0:
                record_signal(
                    strategy=strategy_name or "unknown", signal_type="rejected_exposure"
                )
                increment_risk_rejection(
                    strategy=strategy_name or "unknown", reason="exposure"
                )
                return 0.0, 0.0, "max exposure reached"

        return adjusted, max_capacity, None

    def _validate_trade_strategy_allocation(
        self, strategy_name, adjusted, max_capacity, bankroll, db, effective_mode
    ):
        """Per-strategy allocation check. Returns (adjusted_size, max_capacity, rejection_reason)."""
        if strategy_name and db is not None:
            strategy_allocation = self._get_strategy_allocation(
                strategy_name, bankroll, db, effective_mode
            )
            # Check remaining budget (total allocation minus open exposure)
            remaining_cap = self._strategy_allocation_cap(
                strategy_name, db, effective_mode
            )
            if remaining_cap is not None and remaining_cap <= 0:
                record_signal(
                    strategy=strategy_name, signal_type="rejected_allocation_exhausted"
                )
                increment_risk_rejection(
                    strategy=strategy_name, reason="allocation_exhausted"
                )
                return adjusted, 0.0, f"allocation exhausted for {strategy_name}"
            effective_cap = (
                remaining_cap if remaining_cap is not None else strategy_allocation
            )
            # Use the tighter of strategy allocation and remaining budget
            adjusted = min(adjusted, effective_cap)
            max_capacity = min(max_capacity, effective_cap)
            logger.info(
                f"[risk_manager] Strategy {strategy_name} allocation: ${strategy_allocation:.2f}, "
                f"remaining: ${effective_cap:.2f}, adjusted size: ${adjusted:.2f}"
            )
        return adjusted, max_capacity, None

    def _get_or_update_calibration_and_bias(self, db) -> tuple[dict, Optional[dict]]:
        """Return cached calibration and longshot bias, updating if stale (> 5 minutes)."""
        import time
        from backend.core.learning.calibration_tracker import (
            compute_price_bucket_calibration,
        )
        from backend.core.longshot_bias import LongshotBiasDetector

        now_ts = time.time()

        # Update calibration if needed
        if (
            self._calibration_cache is None
            or self._calibration_cache_time is None
            or now_ts - self._calibration_cache_time > 300
        ):
            try:
                # Recalculate price bucket calibration in 5c increments
                self._calibration_cache = compute_price_bucket_calibration(
                    db, bucket_width=5, window_days=30
                )
                self._calibration_cache_time = now_ts
            except Exception as e:
                logger.error(f"[RiskManager] Failed to update calibration cache: {e}")
                if self._calibration_cache is None:
                    self._calibration_cache = {}

        # Update longshot bias if needed
        if (
            self._longshot_bias_cache is None
            or self._longshot_bias_cache_time is None
            or now_ts - self._longshot_bias_cache_time > 300
        ):
            try:
                detector = LongshotBiasDetector()
                # Compute longshot bias ratio from actual settled trades
                self._longshot_bias_cache = detector.compute_longshot_bias_from_trades(
                    db, price_threshold=0.30, window_days=60
                )
                self._longshot_bias_cache_time = now_ts
            except Exception as e:
                logger.error(f"[RiskManager] Failed to update longshot bias cache: {e}")

        return self._calibration_cache, self._longshot_bias_cache

