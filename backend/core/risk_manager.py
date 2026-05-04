"""Risk manager — validates trades against position size, exposure, drawdown, and confidence rules."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.config import settings
from backend.models.database import SessionLocal, Trade, BotState
from backend.monitoring.hft_metrics import record_signal
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
    breach_reason: str = ""


class RiskManager:
    def __init__(self, settings_obj=None):
        self.s = settings_obj or settings
        self._mode_failure_counts: dict[str, int] = {}

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
    ) -> RiskDecision:
        effective_mode = mode or self.s.TRADING_MODE

        min_confidence = 0.45 if effective_mode == "paper" else getattr(
            self.s, "MIN_CONFIDENCE", self.s.AUTO_APPROVE_MIN_CONFIDENCE
        )
        if confidence < min_confidence:
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_confidence")
            return RiskDecision(False, f"confidence {confidence:.2f} below {min_confidence}", 0.0)

        if not self._breaker_enabled_for_mode("daily_loss", effective_mode):
            logger.debug(
                "[risk_manager] Daily loss breaker disabled for mode=%s — skipping", effective_mode
            )
        elif self._daily_loss_exceeded(db=db, mode=effective_mode):
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_daily_loss")
            return RiskDecision(False, "daily loss limit hit", 0.0)

        if not self._breaker_enabled_for_mode("drawdown", effective_mode):
            logger.debug(
                "[risk_manager] Drawdown breaker disabled for mode=%s — skipping", effective_mode
            )
        else:
            drawdown = self.check_drawdown(bankroll, db=db, mode=effective_mode)
            if drawdown.is_breached:
                record_signal(strategy=strategy_name or "unknown", signal_type="rejected_drawdown")
                return RiskDecision(
                    False, f"drawdown breaker: {drawdown.breach_reason}", 0.0
                )

        if market_ticker and self._has_unsettled_trade(
            market_ticker, db=db, mode=effective_mode
        ):
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_unsettled")
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

        # Paper/testnet bankroll is available cash because entry execution
        # deducts stake immediately; total exposure limits must use equity
        # (cash + already-open stake), otherwise existing positions shrink the
        # denominator and can permanently block new trades. Live bankroll is
        # PM portfolio value, which already includes locked positions.
        exposure_base = bankroll if effective_mode == "live" else bankroll + current_exposure
        max_exposure = exposure_base * self.s.MAX_TOTAL_EXPOSURE_FRACTION
        if current_exposure + adjusted > max_exposure:
            adjusted = max(0.0, max_exposure - current_exposure)
            if adjusted <= 0:
                record_signal(strategy=strategy_name or "unknown", signal_type="rejected_exposure")
                return RiskDecision(False, "max exposure reached", 0.0)

        if slippage is not None and slippage > self.s.SLIPPAGE_TOLERANCE:
            record_signal(strategy=strategy_name or "unknown", signal_type="rejected_slippage")
            return RiskDecision(False, f"slippage {slippage:.4f} > tolerance", 0.0)

        # Per-strategy allocation: use AGI allocation if available, otherwise equal-weight fallback
        if strategy_name and db is not None:
            strategy_allocation = self._get_strategy_allocation(
                strategy_name, bankroll, db
            )
            # Use the strategy allocation as the base size, but don't exceed the adjusted size
            adjusted = min(adjusted, strategy_allocation)
            logger.info(
                f"[risk_manager] Strategy {strategy_name} allocation: ${strategy_allocation:.2f}, adjusted size: ${adjusted:.2f}"
            )

        return RiskDecision(True, "ok", adjusted)

    def check_drawdown(
        self, bankroll: float, db=None, mode: Optional[str] = None
    ) -> DrawdownStatus:
        owns_db = db is None
        if owns_db:
            db = SessionLocal()
        try:
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
                state = db.query(BotState).filter_by(mode=effective_mode).first()
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
        if owns_db:
            db = SessionLocal()
        try:
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
            return daily_pnl <= -self.s.DAILY_LOSS_LIMIT
        except Exception as e:
            logger.error(f"[risk_manager._daily_loss_exceeded] {type(e).__name__}: {e}", exc_info=True)
            return True
        finally:
            if owns_db:
                db.close()

    def _has_unsettled_trade(
        self, market_ticker: str, db=None, mode: Optional[str] = None
    ) -> bool:
        owns_db = db is None
        if owns_db:
            db = SessionLocal()
        try:
            effective_mode = mode or self.s.TRADING_MODE
            count = (
                db.query(func.count(Trade.id))
                .filter(
                    Trade.market_ticker == market_ticker,
                    Trade.settled.is_(False),
                    Trade.trading_mode == effective_mode,
                )
                .scalar()
                or 0
            )
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
                state = db.query(BotState).first()
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
            state = db.query(BotState).first()
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
