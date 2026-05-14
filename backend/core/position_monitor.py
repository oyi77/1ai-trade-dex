"""Position monitor — detect stale open positions on a 30-minute interval.

A position is considered "stale" when it is still open (``Trade.settled is False``)
and has not been refreshed by any monitoring/valuation pass for longer than the
configured stale threshold. Stale positions usually indicate one of:

* The market resolved but the settlement job missed it (no price/source).
* The market_ticker / conditionId is malformed and pricing keeps failing.
* The trade was orphaned (e.g. the originating strategy was disabled mid-flight)
  and nothing is sweeping it.

The monitor does **not** mutate trade state — that is the job of the settlement
pipeline. It only:

1. Identifies stale trades.
2. Marks them via ``Trade.last_sync_at`` once observed (so we don't re-alert).
3. Emits an :class:`AlertManager` warning so operators get a Telegram/Slack ping.
4. Returns the list for callers (e.g. an APScheduler job) to log / forward.

The default interval (30 minutes) is intentional: shorter than the typical
settlement lag, but long enough that a healthy open position should have been
touched at least once by ``position_valuation`` or the settlement loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from loguru import logger

from backend.config import settings
from backend.core.alert_manager import AlertManager
from backend.db.utils import get_db_session
from backend.models.database import Trade


# Stale window. 30 minutes per task spec. Override with env STALE_POSITION_MINUTES.
STALE_INTERVAL_MINUTES: int = int(
    getattr(settings, "STALE_POSITION_MINUTES", 30) or 30
)


@dataclass(frozen=True)
class StalePosition:
    """Lightweight snapshot of a stale open trade."""

    trade_id: int
    market_ticker: Optional[str]
    strategy: Optional[str]
    trading_mode: str
    direction: Optional[str]
    size: Optional[float]
    opened_at: Optional[datetime]
    last_sync_at: Optional[datetime]
    age_minutes: float

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "market_ticker": self.market_ticker,
            "strategy": self.strategy,
            "trading_mode": self.trading_mode,
            "direction": self.direction,
            "size": self.size,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "last_sync_at": (
                self.last_sync_at.isoformat() if self.last_sync_at else None
            ),
            "age_minutes": round(self.age_minutes, 2),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat naive timestamps from SQLite as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _latest_touch(trade: Trade) -> Optional[datetime]:
    """Return the most recent monitoring touch for ``trade``.

    Falls back to ``timestamp`` (entry time) if no sync has happened yet — a
    trade that has never been monitored is considered stale by age alone.
    """
    candidates = [
        _as_aware(getattr(trade, "last_sync_at", None)),
        _as_aware(getattr(trade, "timestamp", None)),
    ]
    valid = [c for c in candidates if c is not None]
    return max(valid) if valid else None


def detect_stale_positions(
    db: Session,
    *,
    stale_after_minutes: int = STALE_INTERVAL_MINUTES,
    trading_modes: Optional[Iterable[str]] = None,
    now: Optional[datetime] = None,
) -> List[StalePosition]:
    """Return all open trades whose last monitor touch is older than the window.

    Args:
        db: Active SQLAlchemy session.
        stale_after_minutes: Threshold in minutes. Default 30.
        trading_modes: Optional filter (e.g. ``{"live", "testnet"}``). When
            ``None`` all modes are scanned.
        now: Reference timestamp for tests. Defaults to ``datetime.now(UTC)``.
    """
    reference = now or _now()
    cutoff = reference - timedelta(minutes=stale_after_minutes)

    query = db.query(Trade).filter(Trade.settled.is_(False))
    if trading_modes:
        query = query.filter(Trade.trading_mode.in_(list(trading_modes)))

    # Pull rows where either last_sync_at or fallback timestamp predates cutoff.
    # We compare in Python to keep tz-aware semantics consistent across SQLite/PG.
    query = query.filter(
        or_(
            Trade.last_sync_at.is_(None),
            Trade.last_sync_at <= cutoff,
        )
    )

    stale: List[StalePosition] = []
    for trade in query.all():
        touched = _latest_touch(trade)
        if touched is None:
            age = float("inf")
        else:
            age = (reference - touched).total_seconds() / 60.0

        if age < stale_after_minutes:
            # last_sync_at was old but entry timestamp is fresh — skip.
            continue

        stale.append(
            StalePosition(
                trade_id=trade.id,
                market_ticker=trade.market_ticker,
                strategy=trade.strategy,
                trading_mode=trade.trading_mode or "paper",
                direction=trade.direction,
                size=trade.size,
                opened_at=_as_aware(trade.timestamp),
                last_sync_at=_as_aware(trade.last_sync_at),
                age_minutes=age if age != float("inf") else -1.0,
            )
        )
    return stale


def mark_position_checked(db: Session, trade_id: int) -> None:
    """Stamp ``last_sync_at`` so a trade is not re-flagged immediately."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade is None:
        return
    trade.last_sync_at = _now()


def _alert_stale(db: Session, stale: List[StalePosition]) -> None:
    if not stale:
        return
    try:
        alerts = AlertManager(db)
    except Exception:  # pragma: no cover - defensive
        logger.exception("AlertManager init failed in position_monitor")
        return

    for entry in stale:
        message = (
            f"Stale open position detected: trade_id={entry.trade_id} "
            f"market={entry.market_ticker} strategy={entry.strategy} "
            f"mode={entry.trading_mode} age_min={entry.age_minutes:.1f}"
        )
        try:
            alerts.create_alert(  # type: ignore[attr-defined]
                kind="stale_position",
                severity="warning",
                message=message,
                meta=entry.to_dict(),
            )
        except Exception:
            # AlertManager API may differ across deployments — fall back to log.
            logger.warning(message)


def run_position_monitor(
    *,
    stale_after_minutes: int = STALE_INTERVAL_MINUTES,
    trading_modes: Optional[Iterable[str]] = None,
    db: Optional[Session] = None,
) -> List[StalePosition]:
    """Top-level entry point — detect, alert, mark, and return stale positions.

    Designed to be invoked by APScheduler on a 30-minute IntervalTrigger:

        scheduler.add_job(
            run_position_monitor,
            IntervalTrigger(minutes=STALE_INTERVAL_MINUTES),
            id="position_monitor",
        )
    """
    if db is not None:
        stale = detect_stale_positions(
            db,
            stale_after_minutes=stale_after_minutes,
            trading_modes=trading_modes,
        )
        _alert_stale(db, stale)
        for entry in stale:
            mark_position_checked(db, entry.trade_id)
        logger.info(
            "Position monitor pass complete",
            stale_count=len(stale),
            threshold_minutes=stale_after_minutes,
        )
        return stale

    with get_db_session() as session:
        stale = detect_stale_positions(
            session,
            stale_after_minutes=stale_after_minutes,
            trading_modes=trading_modes,
        )
        _alert_stale(session, stale)
        for entry in stale:
            mark_position_checked(session, entry.trade_id)
        logger.info(
            "Position monitor pass complete",
            stale_count=len(stale),
            threshold_minutes=stale_after_minutes,
        )
        return stale


async def position_monitor_job() -> None:
    """APScheduler-compatible async wrapper around :func:`run_position_monitor`."""
    import asyncio

    await asyncio.to_thread(run_position_monitor)


__all__ = [
    "STALE_INTERVAL_MINUTES",
    "StalePosition",
    "detect_stale_positions",
    "mark_position_checked",
    "run_position_monitor",
    "position_monitor_job",
]
