"""Strategy rehabilitation — re-enables suspended strategies after paper validation."""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, StrategyConfig, Trade

from loguru import logger


class StrategyRehabilitator:
    """Re-enables disabled strategies if they pass paper-mode validation."""

    @property
    def _s(self):
        from backend.config import settings as _s

        return _s

    @property
    def REHAB_COOLDOWN_DAYS(self):
        return self._s.AGI_REHAB_COOLDOWN_DAYS

    @property
    def REHAB_PAPER_TRADES(self):
        return self._s.AGI_REHAB_MIN_TRADES

    @property
    def REHAB_WIN_RATE_THRESHOLD(self):
        return self._s.AGI_REHAB_WIN_RATE_THRESHOLD

    @property
    def REHAB_ALLOCATION_PCT(self):
        return self._s.AGI_REHAB_ALLOCATION_PCT

    ALLOCATION_STEPS = [0.25, 0.50, 0.75, 1.0]

    def _next_allocation(self, current: float | None) -> float:
        """Return next graduated allocation step. If current is None, return first step."""
        if current is None:
            return self.ALLOCATION_STEPS[0]
        for step in self.ALLOCATION_STEPS:
            if step > current + 0.001:
                return step
        return self.ALLOCATION_STEPS[-1]  # already at max

    def run(self, db: Optional[Session] = None) -> list[str]:
        _owned = db is None
        db = db or SessionLocal()
        rehabilitated = []
        try:
            # Find strategies in rehab: enabled=True but disabled_at set (paper mode)
            disabled = (
                db.query(StrategyConfig).filter(
                    StrategyConfig.enabled.is_(True),
                    StrategyConfig.disabled_at.isnot(None),
                ).all()
            )
            for cfg in disabled:
                if self._is_candidate(cfg, db):
                    if self._passes_validation(cfg, db):
                        cfg.enabled = True
                        cfg.disabled_at = None
                        cfg.trading_mode = "paper"  # Re-enable in paper mode first
                        cfg.rehab_allocation_pct = self._next_allocation(
                            cfg.rehab_allocation_pct
                        )
                        rehabilitated.append(cfg.strategy_name)
                        logger.info(
                            "[Rehabilitation] Re-enabled strategy '%s' in paper mode at %.0f%% allocation",
                            cfg.strategy_name,
                            cfg.rehab_allocation_pct * 100,
                        )

            if rehabilitated:
                db.commit()
            return rehabilitated
        except Exception as e:
            logger.error("[Rehabilitation] Failed: %s", e)
            if _owned:
                try:
                    db.rollback()
                except Exception:
                    logger.exception(
                        "[Rehabilitation] Rollback failed after rehabilitation error"
                    )
            return rehabilitated
        finally:
            if _owned:
                db.close()

    CATASTROPHIC_WR_FLOOR = 0.05
    CATASTROPHIC_MIN_TRADES = 30

    def _is_candidate(self, cfg: StrategyConfig, db: Session) -> bool:
        if self._is_catastrophic(cfg.strategy_name, db):
            return False

        # Use disabled_at for cooldown — not trade timestamps
        # (actively trading strategies always have recent trades)
        if cfg.disabled_at:
            disabled_at = cfg.disabled_at
            if disabled_at.tzinfo is None:
                disabled_at = disabled_at.replace(tzinfo=timezone.utc)

            # Check if strategy has paper trades (short 1-day cooldown)
            has_paper = (
                db.query(Trade)
                .filter(
                    Trade.strategy == cfg.strategy_name,
                    Trade.trading_mode == "paper",
                    Trade.settled.is_(True),
                )
                .first()
            )

            if has_paper:
                cooldown = datetime.now(timezone.utc) - timedelta(days=1)
            else:
                cooldown = datetime.now(timezone.utc) - timedelta(days=self.REHAB_COOLDOWN_DAYS)

            return disabled_at < cooldown

        # No disabled_at — not in rehab
        return False

    def _is_catastrophic(self, strategy: str, db: Session) -> bool:
        from backend.models.outcome_tables import StrategyHealthRecord

        hr = (
            db.query(StrategyHealthRecord)
            .filter(
                StrategyHealthRecord.strategy == strategy,
                StrategyHealthRecord.status == "killed",
            )
            .first()
        )
        if hr and hr.total_trades >= self.CATASTROPHIC_MIN_TRADES:
            if hr.win_rate < self.CATASTROPHIC_WR_FLOOR:
                logger.warning(
                    "[Rehabilitation] Blocked re-enable of '%s': catastrophic WR %.1f%% over %d trades",
                    strategy,
                    hr.win_rate * 100,
                    hr.total_trades,
                )
                return True
        return False

    def _passes_validation(self, cfg: StrategyConfig, db: Session) -> bool:
        """Validate strategy using paper trades + backtest before re-enabling."""
        # Step 1: Check paper trades
        trades = (
            db.query(Trade)
            .filter(
                Trade.strategy == cfg.strategy_name,
                Trade.settled.is_(True),
                Trade.result.in_(["win", "loss"]),
                Trade.trading_mode == "paper",
            )
            .order_by(Trade.timestamp.desc())
            .limit(self.REHAB_PAPER_TRADES * 3)
            .all()
        )

        if len(trades) < self.REHAB_PAPER_TRADES:
            logger.debug(
                "[Rehabilitation] '%s' needs %d paper trades, has %d",
                cfg.strategy_name, self.REHAB_PAPER_TRADES, len(trades),
            )
            return False

        recent = trades[: self.REHAB_PAPER_TRADES]
        wins = sum(1 for t in recent if t.result == "win")
        win_rate = wins / len(recent)

        if win_rate < self.REHAB_WIN_RATE_THRESHOLD:
            logger.debug(
                "[Rehabilitation] '%s' paper WR %.1f%% < %.1f%% threshold",
                cfg.strategy_name, win_rate * 100, self.REHAB_WIN_RATE_THRESHOLD * 100,
            )
            return False

        pnl = sum(t.pnl or 0.0 for t in recent)
        if pnl < 0:
            logger.debug(
                "[Rehabilitation] '%s' paper PnL %.2f < 0",
                cfg.strategy_name, pnl,
            )
            return False

        # Step 2: Run backtest validation
        backtest_ok = self._run_backtest_validation(cfg.strategy_name, db)
        if not backtest_ok:
            return False

        logger.info(
            "[Rehabilitation] '%s' passed paper validation (WR=%.1f%%, PnL=%.2f) + backtest",
            cfg.strategy_name, win_rate * 100, pnl,
        )
        return True

    def _run_backtest_validation(self, strategy_name: str, db: Session) -> bool:
        """Run backtest to validate strategy before re-enabling."""
        try:
            from backend.core.backtester import BacktestEngine, BacktestConfig

            config = BacktestConfig(
                strategy_name=strategy_name,
                start_date=datetime.now(timezone.utc) - timedelta(days=90),
                end_date=datetime.now(timezone.utc),
                initial_bankroll=100.0,
            )
            engine = BacktestEngine(config)

            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = pool.submit(
                            asyncio.run, engine.run(db)
                        ).result(timeout=60)
                else:
                    result = loop.run_until_complete(engine.run(db))
            except RuntimeError:
                result = asyncio.run(engine.run(db))

            if not result or result.total_trades < 5:
                logger.debug(
                    "[Rehabilitation] '%s' backtest insufficient trades (%s)",
                    strategy_name, result.total_trades if result else 0,
                )
                return False

            if result.sharpe_ratio < 0.5:
                logger.debug(
                    "[Rehabilitation] '%s' backtest Sharpe %.2f < 0.5",
                    strategy_name, result.sharpe_ratio,
                )
                return False

            logger.info(
                "[Rehabilitation] '%s' backtest passed: Sharpe=%.2f, WR=%.1f%%, PnL=%.2f, trades=%d",
                strategy_name, result.sharpe_ratio, result.win_rate * 100,
                result.total_pnl, result.total_trades,
            )
            return True

        except Exception as e:
            logger.warning("[Rehabilitation] Backtest failed for '%s': %s", strategy_name, e)
            return False


strategy_rehabilitator = StrategyRehabilitator()
