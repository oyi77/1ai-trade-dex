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
    def REHAB_COOLDOWN_DAYS(self): return self._s.AGI_REHAB_COOLDOWN_DAYS
    @property
    def REHAB_PAPER_TRADES(self): return self._s.AGI_REHAB_MIN_TRADES
    @property
    def REHAB_WIN_RATE_THRESHOLD(self): return self._s.AGI_REHAB_WIN_RATE_THRESHOLD

    def run(self, db: Optional[Session] = None) -> list[str]:
        _owned = db is None
        db = db or SessionLocal()
        rehabilitated = []
        try:
            disabled = db.query(StrategyConfig).filter(not StrategyConfig.enabled).all()
            for cfg in disabled:
                if self._is_candidate(cfg, db):
                    if self._passes_validation(cfg, db):
                        cfg.enabled = True
                        cfg.disabled_at = None
                        rehabilitated.append(cfg.strategy_name)
                        logger.info(
                            "[Rehabilitation] Re-enabled strategy '%s'",
                            cfg.strategy_name,
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
                    logger.exception("[Rehabilitation] Rollback failed after rehabilitation error")
            return rehabilitated
        finally:
            if _owned:
                db.close()

    CATASTROPHIC_WR_FLOOR = 0.05
    CATASTROPHIC_MIN_TRADES = 30

    def _is_candidate(self, cfg: StrategyConfig, db: Session) -> bool:
        if self._is_catastrophic(cfg.strategy_name, db):
            return False

        recent_disabled = (
            db.query(Trade)
            .filter(
                Trade.strategy == cfg.strategy_name,
                Trade.settled.is_(True),
                Trade.trading_mode == "live",
            )
            .order_by(Trade.timestamp.desc())
            .first()
        )
        if not recent_disabled or not recent_disabled.timestamp:
            return False

        last_ts = recent_disabled.timestamp
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)

        cooldown = datetime.now(timezone.utc) - timedelta(days=self.REHAB_COOLDOWN_DAYS)
        return last_ts < cooldown

    def _is_catastrophic(self, strategy: str, db: Session) -> bool:
        from backend.models.outcome_tables import StrategyHealthRecord
        hr = db.query(StrategyHealthRecord).filter(
            StrategyHealthRecord.strategy == strategy,
            StrategyHealthRecord.status == "killed",
        ).first()
        if hr and hr.total_trades >= self.CATASTROPHIC_MIN_TRADES:
            if hr.win_rate < self.CATASTROPHIC_WR_FLOOR:
                logger.warning(
                    "[Rehabilitation] Blocked re-enable of '%s': catastrophic WR %.1f%% over %d trades",
                    strategy, hr.win_rate * 100, hr.total_trades,
                )
                return True
        return False

    def _passes_validation(self, cfg: StrategyConfig, db: Session) -> bool:
        trades = (
            db.query(Trade)
            .filter(
                Trade.strategy == cfg.strategy_name,
                Trade.settled.is_(True),
                Trade.result.in_(["win", "loss"]),
                Trade.trading_mode == "live",
            )
            .order_by(Trade.timestamp.desc())
            .limit(self.REHAB_PAPER_TRADES * 3)
            .all()
        )

        if len(trades) < self.REHAB_PAPER_TRADES:
            return False

        recent = trades[:self.REHAB_PAPER_TRADES]
        wins = sum(1 for t in recent if t.result == "win")
        win_rate = wins / len(recent)

        if win_rate < self.REHAB_WIN_RATE_THRESHOLD:
            return False

        pnl = sum(t.pnl or 0.0 for t in recent)
        if pnl < 0:
            return False

        return True


strategy_rehabilitator = StrategyRehabilitator()
