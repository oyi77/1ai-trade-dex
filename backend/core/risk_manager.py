"""Risk manager — validates trades against position size, exposure, drawdown, and confidence rules."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from contextlib import nullcontext
from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import Trade, BotState, for_update
from backend.monitoring.hft_metrics import record_signal
from backend.monitoring.metrics import increment_risk_rejection
from sqlalchemy import func, or_

logger = logging.getLogger("trading_bot.risk")


def _not_backfill_settlement_source():
    """Include normal settlements and exclude only explicit historical backfills."""

    return or_(
        Trade.settlement_source.is_(None),
        ~Trade.settlement_source.op("LIKE")("backfill_%"),
    )


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    adjusted_size: float


@dataclass
class DrawdownStatus:
    daily_pnl: float
    weekly_pnl: float
    daily_limit_pct: float
    weekly_limit_pct: float
    is_breached: bool
    breach_reason: str


# Immutable Safety Rules - cannot be overridden by strategies or AI
IMMUTABLE_SAFETY_RULES = {
    "max_total_exposure": {
        "default": 0.95,
        "override_env_var": "MAX_TOTAL_EXPOSURE_FRACTION",
        "description": "Never exceed 95% of bankroll in total exposure"
    },
    "max_single_strategy_pct": {
        "default": 0.25,
        "override_env_var": "MAX_SINGLE_STRATEGY_PCT",
        "description": "No strategy can exceed 25% of total capital allocation"
    },
    "daily_loss_floor": {
        "default": -0.10,
        "override_env_var": "DAILY_LOSS_FLOOR_PCT",
        "description": "All strategies pause for 24h if daily PnL < -10% of bankroll"
    },
    "weekly_loss_floor": {
        "default": -0.20,
        "override_env_var": "WEEKLY_LOSS_FLOOR_PCT",
        "description": "Revert to PAPER mode for 7 days if weekly PnL < -20% of bankroll"
    },
    "new_strategy_ramp_pct": {
        "default": 0.01,
        "override_env_var": "NEW_STRATEGY_RAMP_PCT",
        "description": "New strategies start at 1% allocation"
    },
    "new_strategy_min_trades": {
        "default": 20,
        "override_env_var": "NEW_STRATEGY_MIN_TRADES",
        "description": "Scale only after 20 profitable trades"
    },
    "min_archetype_diversity": {
        "default": 5,
        "override_env_var": "MIN_ARCHETYPE_DIVERSITY",
        "description": "At least 5 different archetypes must be active"
    },
    "emergency_kill_switch": {
        "default": True,
        "override_env_var": None,  # Always enabled
        "description": "Single API call stops all trading immediately"
    },
    "audit_trail": {
        "default": True,
        "override_env_var": None,  # Always enabled
        "description": "Every mutation/kill/promotion logged immutably"
    }
}


class RiskManager:
    def __init__(self, settings_obj=None):
        self.s = settings_obj or settings
        self._mode_failure_counts: dict[str, int] = {}
        self._safety_rules = self._load_safety_rules()

    def _get_bankroll(self, db, mode: str) -> float:
        state = for_update(db, db.query(BotState).filter_by(mode=mode)).first()
        if state and state.bankroll is not None:
            return float(state.bankroll)
        return self.s.INITIAL_BANKROLL

    def _load_safety_rules(self) -> dict:
        """Load immutable safety rules with environment variable overrides."""
        import os

        rules = {}
        for rule_name, rule_config in IMMUTABLE_SAFETY_RULES.items():
            # Start with default value
            value = rule_config["default"]

            # Check for environment variable override
            env_var = rule_config.get("override_env_var")
            if env_var:
                env_value = os.environ.get(env_var)
                if env_value is not None:
                    try:
                        # Convert to appropriate type
                        if isinstance(value, float):
                            value = float(env_value)
                        elif isinstance(value, int):
                            value = int(env_value)
                        elif isinstance(value, bool):
                            value = env_value.lower() in ("true", "1", "yes")
                    except ValueError:
                        logger.warning(f"Invalid value for {env_var}={env_value}, using default {value}")

            rules[rule_name] = value

        return rules

    def _breaker_enabled_for_mode(self, breaker: str, mode: str) -> bool:
        """Check whether a circuit breaker is enabled for the given trading mode.

        breaker: "drawdown" or "daily_loss"
        mode: "paper", "testnet", or "live"

        Paper mode defaults to breaker-disabled so it can run infinitely for
        backtest, frontest, and improvement loops. Testnet and live default
        to breaker-enabled for capital safety.
        """
        if breaker == "drawdown":
            config = self.s.DRAWDOWN_BREAKER_ENABLED_PER_MODE
        elif breaker == "daily_loss":
            config = self.s.DAILY_LOSS_LIMIT_ENABLED_PER_MODE
        else:
            return True
        return config.get(mode, True)

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
    ) -> RiskDecision:
        effective_mode = mode or self.s.TRADING_MODE

        from backend.strategies.registry import STRATEGY_REGISTRY
        params = None
        if strategy_name in STRATEGY_REGISTRY:
            params = dict(getattr(STRATEGY_REGISTRY[strategy_name], "default_params", {}))
        if params and params.get("_force_disabled", False):
            return RiskDecision(False, "strategy explicitly disabled", 0.0)

        min_confidence = self._get_confidence_threshold(effective_mode, strategy_name)
        if confidence < min_confidence:
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_confidence")
            increment_risk_rejection(strategy=strategy_name or "unknown", reason="confidence")
            return RiskDecision(False, f"confidence {confidence:.2f} below {min_confidence}", 0.0)

        bias_weight = getattr(self.s, 'LONGSHOT_NO_BIAS_WEIGHT', 0.0)
        if bias_weight > 0 and direction:
            original_conf = confidence
            if direction.upper() == 'NO':
                confidence = min(1.0, confidence * (1 + bias_weight))
            elif direction.upper() == 'YES':
                confidence = confidence * (1 - bias_weight * 0.5)
            if confidence != original_conf:
                logger.info("[risk_manager] Applied NO-bias: %s -> %.2f -> %.2f", direction, original_conf, confidence)

        cat_enabled = getattr(self.s, 'CATEGORY_CONFIDENCE_ENABLED', False)
        if cat_enabled and category:
            cat_multipliers = getattr(self.s, 'CATEGORY_CONFIDENCE_MULTIPLIER', {})
            multiplier = cat_multipliers.get(category.lower(), 1.0)
            if multiplier != 1.0:
                pre_cat = confidence
                confidence = min(1.0, confidence * multiplier)
                logger.info("[risk_manager] Applied category multiplier: %s %.2f x%.2f -> %.2f", category, pre_cat, multiplier, confidence)

        if not self._breaker_enabled_for_mode("daily_loss", effective_mode):
            logger.debug(
                "[risk_manager] Daily loss breaker disabled for mode=%s — skipping", effective_mode
            )
        elif self._daily_loss_exceeded(db=db, mode=effective_mode):
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_daily_loss")
            increment_risk_rejection(strategy=strategy_name or "unknown", reason="daily_loss")
            return RiskDecision(False, "daily loss limit hit", 0.0)

        if not self._breaker_enabled_for_mode("drawdown", effective_mode):
            logger.debug(
                "[risk_manager] Drawdown breaker disabled for mode=%s — skipping", effective_mode
            )
        else:
            drawdown = self.check_drawdown(bankroll, db=db, mode=effective_mode)
            if drawdown.is_breached:
                record_signal(strategy=strategy_name or "unknown", signal_type="rejected_drawdown")
                increment_risk_rejection(strategy=strategy_name or "unknown", reason="drawdown")
                return RiskDecision(
                    False, f"drawdown breaker: {drawdown.breach_reason}", 0.0
                )

        if market_ticker and self._has_unsettled_trade(
            market_ticker, db=db, mode=effective_mode, direction=direction
        ):
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_unsettled")
            increment_risk_rejection(strategy=strategy_name or "unknown", reason="unsettled")
            return RiskDecision(
                False, f"unsettled trade exists for {market_ticker}", 0.0
            )

        # Live bankroll = PM portfolio value (includes locked positions);
        # available cash = portfolio minus open exposure.
        if effective_mode == "live":
            available_cash = max(0.0, bankroll - current_exposure)
            max_position = available_cash * self.s.MAX_POSITION_FRACTION
        else:
            max_position = bankroll * self.s.MAX_POSITION_FRACTION
        adjusted = min(size, max_position)

        # Global max trade size ceiling (immutable safety rule)
        adjusted = min(adjusted, self.s.MAX_TRADE_SIZE)

        # Paper/testnet bankroll is available cash because entry execution
        # deducts stake immediately; total exposure limits must use equity
        # (cash + already-open stake), otherwise existing positions shrink the
        # denominator and can permanently block new trades. Live bankroll is
        # PM portfolio value, which already includes locked positions.
        exposure_base = bankroll if effective_mode == "live" else bankroll + current_exposure
        # Use immutable safety rule for max total exposure
        max_exposure = exposure_base * self._safety_rules["max_total_exposure"]
        if current_exposure + adjusted > max_exposure:
            adjusted = max(0.0, max_exposure - current_exposure)
            if adjusted <= 0:
                record_signal(strategy=strategy_name or "unknown", signal_type="rejected_exposure")
                increment_risk_rejection(strategy=strategy_name or "unknown", reason="exposure")
                return RiskDecision(False, "max exposure reached", 0.0)

        if slippage is not None and slippage > self.s.SLIPPAGE_TOLERANCE:
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_slippage")
            increment_risk_rejection(strategy=strategy_name or "unknown", reason="slippage")
            return RiskDecision(False, f"slippage {slippage:.4f} > tolerance", 0.0)

        # Per-strategy allocation: use AGI allocation if available, otherwise equal-weight fallback
        if strategy_name and db is not None:
            strategy_allocation = self._get_strategy_allocation(
                strategy_name, bankroll, db
            )
            # Check remaining budget (total allocation minus open exposure)
            remaining_cap = self._strategy_allocation_cap(strategy_name, db, effective_mode)
            if remaining_cap is not None and remaining_cap <= 0:
                record_signal(strategy=strategy_name, signal_type="rejected_allocation_exhausted")
                increment_risk_rejection(strategy=strategy_name, reason="allocation_exhausted")
                return RiskDecision(False, f"allocation exhausted for {strategy_name}", 0.0)
            effective_cap = remaining_cap if remaining_cap is not None else strategy_allocation
            # Use the tighter of strategy allocation and remaining budget
            adjusted = min(adjusted, effective_cap)
            logger.info(
                f"[risk_manager] Strategy {strategy_name} allocation: ${strategy_allocation:.2f}, "
                f"remaining: ${effective_cap:.2f}, adjusted size: ${adjusted:.2f}"
            )

        return RiskDecision(True, "ok", adjusted)

    def check_drawdown(
        self, bankroll: float, db=None, mode: Optional[str] = None
    ) -> DrawdownStatus:
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                now = datetime.now(timezone.utc)
                day_start = now - timedelta(hours=24)
                week_start = now - timedelta(days=7)

                daily_pnl = (
                    db.query(func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0))
                    .filter(
                        Trade.settled.is_(True),
                        Trade.settlement_time >= day_start,
                        Trade.trading_mode == effective_mode,
                        _not_backfill_settlement_source(),
                    )
                    .scalar()
                    or 0.0
                )

                weekly_pnl = (
                    db.query(func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0))
                    .filter(
                        Trade.settled.is_(True),
                        Trade.settlement_time >= week_start,
                        Trade.trading_mode == effective_mode,
                        _not_backfill_settlement_source(),
                    )
                    .scalar()
                    or 0.0
                )

                # Use the higher of current bankroll or effective initial bankroll to prevent
                # death spiral: depleted bankroll → tiny limit → can't trade → can't recover.
                # Reads DB-backed initial (which includes top-ups) when available.
                effective_initial = self.s.INITIAL_BANKROLL
                if db is not None:
                    state = for_update(db, db.query(BotState).filter_by(mode=effective_mode)).first()
                    if state is not None:
                        if effective_mode == "paper" and state.paper_initial_bankroll is not None:
                            effective_initial = float(state.paper_initial_bankroll)
                        elif effective_mode == "testnet" and state.testnet_initial_bankroll is not None:
                            effective_initial = float(state.testnet_initial_bankroll)
                base_bankroll = max(bankroll, effective_initial)
                daily_limit = base_bankroll * self.s.DAILY_DRAWDOWN_LIMIT_PCT
                weekly_limit = base_bankroll * self.s.WEEKLY_DRAWDOWN_LIMIT_PCT

                breach_reason = ""
                is_breached = False

                if daily_pnl <= -daily_limit:
                    is_breached = True
                    breach_reason = f"24h loss ${abs(daily_pnl):.2f} exceeds {self.s.DAILY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${daily_limit:.2f})"
                elif weekly_pnl <= -weekly_limit:
                    is_breached = True
                    breach_reason = f"7d loss ${abs(weekly_pnl):.2f} exceeds {self.s.WEEKLY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${weekly_limit:.2f})"

                return DrawdownStatus(
                    daily_pnl=daily_pnl,
                    weekly_pnl=weekly_pnl,
                    daily_limit_pct=self.s.DAILY_DRAWDOWN_LIMIT_PCT,
                    weekly_limit_pct=self.s.WEEKLY_DRAWDOWN_LIMIT_PCT,
                    is_breached=is_breached,
                    breach_reason=breach_reason,
                )
        except Exception as e:
                logger.error(f"[risk_manager.check_drawdown] {type(e).__name__}: {e}", exc_info=True)
                return DrawdownStatus(
                    0.0,
                    0.0,
                    self.s.DAILY_DRAWDOWN_LIMIT_PCT,
                    self.s.WEEKLY_DRAWDOWN_LIMIT_PCT,
                    True,
                    "DB error during drawdown check",
                )
        finally:
                if owns_db:
                    db.close()

    def _daily_loss_exceeded(self, db=None, mode: Optional[str] = None) -> bool:
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                now = datetime.now(timezone.utc)
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                daily_pnl = (
                    db.query(func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0))
                    .filter(
                        Trade.settled.is_(True),
                        Trade.settlement_time >= today_start,
                        Trade.trading_mode == effective_mode,
                        _not_backfill_settlement_source(),
                    )
                    .scalar()
                    or 0.0
                )
                # Percentage-based daily loss limit: scales with bankroll.
                # Falls back to flat DAILY_LOSS_LIMIT if DAILY_LOSS_LIMIT_PCT is not set.
                daily_loss_limit_pct = getattr(self.s, 'DAILY_LOSS_LIMIT_PCT', None)
                if daily_loss_limit_pct:
                    bankroll = self._get_bankroll(db, effective_mode)
                    daily_limit = bankroll * daily_loss_limit_pct
                else:
                    daily_limit = self.s.DAILY_LOSS_LIMIT
                return daily_pnl <= -daily_limit
        except Exception as e:
                logger.error(f"[risk_manager._daily_loss_exceeded] {type(e).__name__}: {e}", exc_info=True)
                return True
        finally:
                if owns_db:
                    db.close()

    def _has_unsettled_trade(
        self, market_ticker: str, db=None, mode: Optional[str] = None, direction: Optional[str] = None
    ) -> bool:
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                query = db.query(func.count(Trade.id)).filter(
                    Trade.market_ticker == market_ticker,
                    Trade.settled.is_(False),
                    Trade.trading_mode == effective_mode,
                )
                # Per-direction check: YES and NO positions can coexist on the same market
                if direction is not None:
                    query = query.filter(Trade.direction == direction)
                count = query.scalar() or 0
                return count > 0
        except Exception as e:
                logger.error(f"[risk_manager._has_unsettled_trade] {type(e).__name__}: {e}", exc_info=True)
                return True
        finally:
                if owns_db:
                    db.close()

    def _count_enabled_strategies(self, db) -> int:
        """Count the number of enabled strategies in StrategyConfig."""
        try:
            from backend.models.database import StrategyConfig
            enabled_count = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))
                .count()
            )
            return enabled_count
        except Exception as e:
            logger.error(f"[risk_manager._count_enabled_strategies] {type(e).__name__}: {e}", exc_info=True)
            return 0

    def _get_strategy_allocation(self, strategy_name: str, bankroll: float, db) -> float:
        """Get strategy allocation using AGI allocation if available, otherwise equal-weight fallback."""
        # Check if AGI bankroll allocation is enabled
        if getattr(self.s, 'AGI_BANKROLL_ALLOCATION_ENABLED', False):
            # Try to get AGI allocation from BotState.misc_data
            try:
                state = for_update(db, db.query(BotState)).first()
                if state and state.misc_data:
                    misc = json.loads(state.misc_data)
                    allocations = misc.get("allocations", {})
                    if strategy_name in allocations:
                        allocation = float(allocations[strategy_name])
                        # Cap at MAX_POSITION_FRACTION
                        max_position = bankroll * getattr(self.s, 'MAX_POSITION_FRACTION', 0.25)
                        return min(allocation, max_position)
            except Exception as e:
                logger.error(f"[risk_manager._get_strategy_allocation] Error reading AGI allocation: {type(e).__name__}: {e}", exc_info=True)

        # Fallback: equal-weight allocation
        enabled_count = self._count_enabled_strategies(db)
        if enabled_count == 0:
            # No enabled strategies - use MAX_POSITION_FRACTION
            return bankroll * getattr(self.s, 'MAX_POSITION_FRACTION', 0.25)

        # Calculate equal share
        max_total_exposure = bankroll * getattr(self.s, 'MAX_TOTAL_EXPOSURE_FRACTION', 0.70)
        equal_share = max_total_exposure / enabled_count

        # Cap at MAX_POSITION_FRACTION
        max_position = bankroll * getattr(self.s, 'MAX_POSITION_FRACTION', 0.25)
        return min(equal_share, max_position)

    def _strategy_allocation_cap(
        self, strategy_name: str, db, mode: str
    ) -> Optional[float]:
        """Return remaining allocation budget for a strategy, or None if no allocation exists."""
        try:
            state = for_update(db, db.query(BotState)).first()
            if not state or not state.misc_data:
                return None
            misc = json.loads(state.misc_data)
            allocations = misc.get("allocations", {})
            if strategy_name not in allocations:
                return None
            total_budget = float(allocations[strategy_name])
            strategy_exposure = (
                db.query(func.coalesce(func.sum(Trade.size), 0.0))
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.settled.is_(False),
                    Trade.trading_mode == mode,
                )
                .scalar()
                or 0.0
            )
            remaining = total_budget - float(strategy_exposure)
            return max(0.0, remaining)
        except Exception as e:
            logger.error(f"[risk_manager._strategy_allocation_cap] {type(e).__name__}: {e}", exc_info=True)
            return None

    def _get_confidence_threshold(self, trading_mode: str, strategy_name: Optional[str] = None) -> float:
        """Get confidence threshold for trade approval, respecting regime routing."""
        # Start with base confidence from settings
        base_confidence = getattr(
            self.s, "MIN_CONFIDENCE", self.s.AUTO_APPROVE_MIN_CONFIDENCE
        )

        # Apply regime multiplier if enabled
        if getattr(self.s, 'REGIME_ROUTING_ENABLED', False):
            regime_multiplier = self._get_regime_multiplier(strategy_name)
            threshold = base_confidence * regime_multiplier
        else:
            threshold = base_confidence

        # Cap at 0.95 maximum
        return min(threshold, 0.95)

    def check_drawdown_floors(
        self, bankroll: float, db=None, mode: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check if daily/weekly loss floors have been breached.

        Args:
            bankroll: Current bankroll amount
            db: Database session (optional)
            mode: Trading mode (optional)

        Returns:
            Tuple of (floor_breached, action_taken) where action_taken describes what happened
        """
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
            now = datetime.now(timezone.utc)
            day_start = now - timedelta(hours=24)
            week_start = now - timedelta(days=7)

            # Calculate daily and weekly PnL
            daily_pnl = (
                db.query(func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0))
                .filter(
                    Trade.settled.is_(True),
                    Trade.settlement_time >= day_start,
                    Trade.trading_mode == effective_mode,
                    _not_backfill_settlement_source(),
                )
                .scalar()
                or 0.0
            )

            weekly_pnl = (
                db.query(func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0))
                .filter(
                    Trade.settled.is_(True),
                    Trade.settlement_time >= week_start,
                    Trade.trading_mode == effective_mode,
                    _not_backfill_settlement_source(),
                )
                .scalar()
                or 0.0
            )

            # Use the higher of current bankroll or effective initial bankroll
            effective_initial = self.s.INITIAL_BANKROLL
            if db is not None:
                state = for_update(db, db.query(BotState).filter_by(mode=effective_mode)).first()
                if state is not None:
                    if effective_mode == "paper" and state.paper_initial_bankroll is not None:
                        effective_initial = float(state.paper_initial_bankroll)
                    elif effective_mode == "testnet" and state.testnet_initial_bankroll is not None:
                        effective_initial = float(state.testnet_initial_bankroll)
            base_bankroll = max(bankroll, effective_initial)

            # Check daily loss floor
            daily_floor = base_bankroll * self.s.DAILY_LOSS_FLOOR_PCT
            if daily_pnl < daily_floor:
                # Pause all strategies for 24 hours
                pause_until = now + timedelta(hours=24)

                # Store pause timestamp in BotState.misc_data
                if db is not None:
                    state = for_update(db, db.query(BotState).filter_by(mode=effective_mode)).first()
                    if state is None:
                        state = BotState(mode=effective_mode, misc_data={})
                        db.add(state)

                    state.misc_data = state.misc_data or {}
                    state.misc_data["pause_until"] = pause_until.isoformat()
                    db.commit()

                # Emit SSE event
                self._publish_event("daily_loss_floor_triggered", {
                    "bankroll": bankroll,
                    "daily_pnl": daily_pnl,
                    "daily_floor_pct": self.s.DAILY_LOSS_FLOOR_PCT,
                    "daily_floor_amount": daily_floor,
                    "pause_until": pause_until.isoformat(),
                    "action": "all_strategies_paused"
                })

                return True, "all_strategies_paused_24h"

            # Check weekly loss floor
            weekly_floor = base_bankroll * self.s.WEEKLY_LOSS_FLOOR_PCT
            if weekly_pnl < weekly_floor:
                # Revert to PAPER mode for 7 days
                paper_until = now + timedelta(days=7)

                # Store paper mode timestamp in BotState.misc_data
                if db is not None:
                    state = for_update(db, db.query(BotState).filter_by(mode=effective_mode)).first()
                    if state is None:
                        state = BotState(mode=effective_mode, misc_data={})
                        db.add(state)

                    state.misc_data = state.misc_data or {}
                    state.misc_data["paper_until"] = paper_until.isoformat()
                    db.commit()

                # Emit SSE event
                self._publish_event("weekly_loss_floor_triggered", {
                    "bankroll": bankroll,
                    "weekly_pnl": weekly_pnl,
                    "weekly_floor_pct": self.s.WEEKLY_LOSS_FLOOR_PCT,
                    "weekly_floor_amount": weekly_floor,
                    "paper_until": paper_until.isoformat(),
                    "action": "reverted_to_paper_mode"
                })

                return True, "reverted_to_paper_mode_7d"

            return False, None

        except Exception as e:
            logger.error(f"[risk_manager.check_drawdown_floors] {type(e).__name__}: {e}", exc_info=True)
            return False, f"error_during_floor_check: {type(e).__name__}"
        finally:
            if owns_db:
                db.close()

    def _publish_event(self, event_type: str, payload: dict):
        """Publish SSE event via event bus."""
        try:
            from backend.core.event_bus import publish_event
            publish_event(event_type, payload)
        except ImportError:
            logger.warning(f"[risk_manager] Event bus not available, skipping SSE event: {event_type}")
        except Exception as e:
            logger.error(f"[risk_manager._publish_event] {type(e).__name__}: {e}", exc_info=True)

    def _get_regime_multiplier(self, strategy_name: Optional[str] = None) -> float:
        """Get current regime confidence multiplier from RegimeConfidenceRouter."""
        try:
            from backend.application.meta.regime_router import RegimeConfidenceRouter
            router = RegimeConfidenceRouter()
            return router.get_multiplier(strategy_name or "")
        except ImportError:
            # Fallback to default multiplier if regime router not available
            return 1.0
