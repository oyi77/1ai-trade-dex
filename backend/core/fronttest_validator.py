"""Fronttest validation — 14-day paper-trial gate before live parameter changes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import SessionLocal, StrategyProposal, Trade

logger = logging.getLogger("trading_bot.fronttest")


class FronttestValidator:
    """Validates that a parameter change survives a paper-trial period before going live."""

    def __init__(self, trial_days: int = None, min_trades: int = None):
        self.trial_days = trial_days if trial_days is not None else settings.AGI_FRONTTEST_DAYS
        self.min_trades = min_trades if min_trades is not None else settings.AGI_FRONTTEST_MIN_TRADES

    def can_go_live(self, proposal_id: int, db: Optional[Session] = None) -> dict:
        _owned = db is None
        db = db or SessionLocal()
        try:
            proposal = db.query(StrategyProposal).filter(
                StrategyProposal.id == proposal_id
            ).first()
            if not proposal:
                return {"approved": False, "reason": "proposal not found"}

            if proposal.admin_decision not in ("approved", "executed"):
                return {"approved": False, "reason": f"proposal status is {proposal.admin_decision}"}

            executed = proposal.executed_at
            if not executed:
                return {"approved": False, "reason": "proposal not yet executed"}

            if executed.tzinfo is None:
                executed = executed.replace(tzinfo=timezone.utc)

            elapsed = (datetime.now(timezone.utc) - executed).days
            if elapsed < self.trial_days:
                remaining = self.trial_days - elapsed
                return {
                    "approved": False,
                    "reason": f"trial period incomplete ({remaining} days remaining)",
                    "elapsed_days": elapsed,
                    "required_days": self.trial_days,
                }

            strategy = proposal.strategy_name
            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy,
                    Trade.trading_mode == "paper",
                    Trade.timestamp >= executed,
                    Trade.settled.is_(True),
                )
                .all()
            )

            settled = [t for t in trades if t.result in ("win", "loss")]
            if len(settled) < self.min_trades:
                return {
                    "approved": False,
                    "reason": f"insufficient paper trades ({len(settled)}/{self.min_trades})",
                    "elapsed_days": elapsed,
                    "trade_count": len(settled),
                }

            wins = sum(1 for t in settled if t.result == "win")
            win_rate = wins / len(settled)
            pnl = sum(t.pnl or 0.0 for t in settled)

            if win_rate < settings.AGI_FRONTTEST_MIN_WIN_RATE:
                return {
                    "approved": False,
                    "reason": f"paper win rate too low ({win_rate:.0%})",
                    "elapsed_days": elapsed,
                    "trade_count": len(settled),
                    "win_rate": win_rate,
                    "pnl": pnl,
                }

            return {
                "approved": True,
                "reason": "fronttest passed",
                "elapsed_days": elapsed,
                "trade_count": len(settled),
                "win_rate": win_rate,
                "pnl": pnl,
            }
        except Exception as e:
            logger.error("Fronttest validation failed for proposal %d: %s", proposal_id, e)
            return {"approved": False, "reason": f"validation error: {e}"}
        finally:
            if _owned:
                db.close()

    def validate_all_pending(self, db: Optional[Session] = None) -> list[dict]:
        _owned = db is None
        db = db or SessionLocal()
        results = []
        try:
            proposals = db.query(StrategyProposal).filter(
                StrategyProposal.admin_decision == "executed",
                StrategyProposal.executed_at.isnot(None),
            ).all()

            for p in proposals:
                result = self.can_go_live(p.id, db=db)
                result["proposal_id"] = p.id
                result["strategy"] = p.strategy_name
                results.append(result)

            return results
        finally:
            if _owned:
                db.close()


fronttest_validator = FronttestValidator()
