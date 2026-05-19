"""
AccountSummarizer — Generates paper & live account summaries.

Sources:
- DB: BotState (balance, mode, last updated)
- DB: Trade aggregation (daily PnL, win rate)
- DB: Open positions from positions table
- API: Polymarket Data API for real-time position values
- On-chain: pUSD balance via RPC

Output: AccountSummary dict with balance, PnL, positions, equity curve.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from loguru import logger

from backend.config import settings
from backend.models.database import SessionLocal, BotState, Trade


@dataclass
class AccountSummary:
    """Summary of a trading account (paper or live)."""

    mode: str = ""  # paper | live
    status: str = "unknown"  # healthy | warning | critical | error

    # Balance
    balance: float = 0.0
    initial_balance: float = 0.0
    equity: float = 0.0  # balance + unrealized PnL
    free_capital: float = 0.0

    # Positions
    open_positions: int = 0
    open_position_value: float = 0.0
    total_unrealized_pnl: float = 0.0

    # PnL
    pnl_total: float = 0.0
    pnl_daily: float = 0.0
    pnl_weekly: float = 0.0
    pnl_monthly: float = 0.0

    # Performance
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0

    # Meta
    last_updated: str = ""
    last_trade_time: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class AccountSummarizer:
    """
    Generates comprehensive account summaries.

    Usage:
        summarizer = AccountSummarizer()
        summary = await summarizer.summarize(mode="paper")
        all_summaries = await summarizer.summarize_all()
    """

    def __init__(self):
        pass

    async def summarize_all(self) -> Dict[str, dict]:
        """Summarize all active modes (paper + live)."""
        summaries: Dict[str, dict] = {}
        active_modes = list(settings.active_modes_set)

        for mode in active_modes:
            try:
                summary = await self.summarize(mode)
                summaries[mode] = summary.to_dict()
            except Exception as exc:
                logger.opt(exception=True).error(
                    f"[AccountSummarizer] Failed for mode={mode}: {exc}"
                )
                summaries[mode] = AccountSummary(
                    mode=mode, status="error", error=str(exc)
                ).to_dict()

        return summaries

    async def summarize(self, mode: str) -> AccountSummary:
        """Generate a full summary for a single mode (paper or live)."""
        summary = AccountSummary(mode=mode)

        try:
            with SessionLocal() as db:
                # ── BotState (balance, mode state) ──
                bot_state = (
                    db.query(BotState)
                    .filter(BotState.mode == mode)
                    .order_by(BotState.updated_at.desc())
                    .first()
                )

                if bot_state:
                    summary.balance = float(bot_state.balance or 0.0)
                    summary.equity = float(bot_state.equity or 0.0)
                    summary.initial_balance = float(bot_state.initial_balance or 0.0)
                    summary.last_updated = (
                        bot_state.updated_at.isoformat()
                        if bot_state.updated_at
                        else ""
                    )

                    # Open positions from misc_data
                    if bot_state.misc_data:
                        misc = bot_state.misc_data
                        if isinstance(misc, str):
                            try:
                                misc = json.loads(misc)
                            except (json.JSONDecodeError, TypeError):
                                misc = {}
                        summary.open_positions = int(misc.get("open_positions", 0))
                        summary.open_position_value = float(
                            misc.get("open_position_value", 0.0)
                        )
                        summary.total_unrealized_pnl = float(
                            misc.get("total_unrealized_pnl", 0.0)
                        )

                # ── Trade stats ──
                now = datetime.now(timezone.utc)

                trades = (
                    db.query(Trade)
                    .filter(
                        Trade.mode == mode,
                        Trade.settled == True,  # noqa: E712
                    )
                    .all()
                )

                if trades:
                    # Total trades
                    summary.total_trades = len(trades)

                    # PnL
                    summary.pnl_total = sum(t.pnl or 0.0 for t in trades)

                    # Find last trade time
                    valid_times = [
                        t.timestamp for t in trades if t.timestamp is not None
                    ]
                    if valid_times:
                        summary.last_trade_time = max(valid_times).isoformat()

                    # Time-filtered PnL
                    for t in trades:
                        ts = t.timestamp
                        if ts:
                            if ts >= now - timedelta(days=1):
                                summary.pnl_daily += t.pnl or 0.0
                            if ts >= now - timedelta(days=7):
                                summary.pnl_weekly += t.pnl or 0.0
                            if ts >= now - timedelta(days=30):
                                summary.pnl_monthly += t.pnl or 0.0

                    # Win rate
                    wins = sum(1 for t in trades if (t.pnl or 0.0) > 0)
                    summary.win_rate = wins / len(trades) if trades else 0.0

                    # Profit factor
                    gross_win = sum(
                        t.pnl or 0.0 for t in trades if (t.pnl or 0.0) > 0
                    )
                    gross_loss = abs(
                        sum(
                            t.pnl or 0.0
                            for t in trades
                            if (t.pnl or 0.0) <= 0
                        )
                    )
                    summary.profit_factor = (
                        gross_win / gross_loss if gross_loss > 0 else 999.0
                    )

                    # Avgs
                    win_trades = [t for t in trades if (t.pnl or 0.0) > 0]
                    loss_trades = [t for t in trades if (t.pnl or 0.0) <= 0]
                    summary.avg_win = (
                        gross_win / len(win_trades) if win_trades else 0.0
                    )
                    summary.avg_loss = (
                        gross_loss / len(loss_trades) if loss_trades else 0.0
                    )

                # ── Free capital ──
                summary.free_capital = summary.equity - summary.open_position_value

                # ── Status determination ──
                summary.status = self._determine_status(summary)

        except Exception as exc:
            logger.opt(exception=True).error(
                f"[AccountSummarizer] Failed for mode={mode}: {exc}"
            )
            summary.status = "error"
            summary.error = str(exc)

        return summary

    def _determine_status(self, summary: AccountSummary) -> str:
        """Determine account health status."""
        # Check for obvious issues
        if summary.balance <= 0 and summary.total_trades > 0:
            return "critical"
        if summary.pnl_daily < -settings.RISK_DAILY_LOSS_LIMIT:
            return "critical"
        if summary.pnl_total < -500:
            return "warning"
        if summary.total_trades == 0:
            return "inactive" if summary.initial_balance > 0 else "new"
        return "healthy"

    async def get_equity_curve(
        self, mode: str, days: int = 30
    ) -> List[Dict[str, Any]]:
        """Build equity curve from settled trades."""
        curve: List[Dict[str, Any]] = []

        try:
            with SessionLocal() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                trades = (
                    db.query(Trade)
                    .filter(
                        Trade.mode == mode,
                        Trade.settled == True,  # noqa: E712
                        Trade.timestamp >= cutoff,
                    )
                    .order_by(Trade.timestamp.asc())
                    .all()
                )

                cumulative = 0.0
                for t in trades:
                    cumulative += t.pnl or 0.0
                    curve.append({
                        "timestamp": t.timestamp.isoformat() if t.timestamp else "",
                        "pnl": t.pnl or 0.0,
                        "cumulative_pnl": cumulative,
                    })

        except Exception as exc:
            logger.debug(f"[AccountSummarizer] Equity curve error: {exc}")

        return curve
