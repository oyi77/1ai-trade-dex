from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.core.copy_source import CopyPolicyConfig, CopySignalData, CopySource
from backend.models.database import CopyTraderEntry, Trade, TradeContext


class InternalMirrorSource(CopySource):
    def __init__(
        self,
        db_session: Session,
        policy: CopyPolicyConfig | None,
        followed_strategies: list[str] | None = None,
    ) -> None:
        self._db = db_session
        self._policy = policy
        self._followed = followed_strategies or []

    def get_name(self) -> str:
        return "internal_mirror"

    async def fetch_signals(self) -> list[CopySignalData]:
        if not self._followed or self._db is None:
            return []

        max_delay = self._policy.max_delay_seconds if self._policy else 60
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_delay)

        recent_trades = (
            self._db.query(Trade)
            .join(TradeContext, Trade.id == TradeContext.trade_id, isouter=True)
            .filter(
                TradeContext.strategy.in_(self._followed),
                Trade.created_at >= cutoff,
                Trade.status == "filled",
            )
            .all()
        )

        signals: list[CopySignalData] = []
        for trade in recent_trades:
            already_mirrored = (
                self._db.query(CopyTraderEntry)
                .filter(
                    CopyTraderEntry.wallet == trade.wallet_address if hasattr(trade, "wallet_address") else "",
                    CopyTraderEntry.condition_id == trade.condition_id,
                    CopyTraderEntry.side == trade.side,
                )
                .first()
            )
            if already_mirrored:
                continue

            ctx = self._db.query(TradeContext).filter(TradeContext.trade_id == trade.id).first()
            confidence = ctx.confidence if ctx and ctx.confidence is not None else 0.5

            signals.append(
                CopySignalData(
                    source_name=self.get_name(),
                    leader_address=getattr(trade, "wallet_address", "internal"),
                    condition_id=trade.condition_id,
                    side=trade.side,
                    raw_size=float(trade.size or 0),
                    confidence=confidence,
                    captured_at=trade.created_at or datetime.now(timezone.utc),
                )
            )

        return signals

    async def is_healthy(self) -> bool:
        return True
