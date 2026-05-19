"""
StrategyPerformanceTracker — Fetches and analyzes strategy performance.

Sources:
- DB: Trade table (realized PnL, win rate)
- DB: StrategyConfig table (enabled/disabled status, params)
- Memory: heartbeat timestamps (freshness check)
- API: Polymarket open positions for real-time values

Output: StrategyReport per strategy with comprehensive metrics.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from loguru import logger

from backend.config import settings

from backend.models.database import (
    SessionLocal,
    Trade,
    StrategyConfig,
    BotState,
)


@dataclass
class StrategyReport:
    """Complete performance report for a single strategy."""

    name: str = ""
    mode: str = "paper"
    status: str = "unknown"  # healthy | warning | critical | disabled | error

    # Trade counts
    total_trades: int = 0
    recent_trades_7d: int = 0
    recent_trades_30d: int = 0

    # Performance
    pnl: float = 0.0
    pnl_7d: float = 0.0
    pnl_30d: float = 0.0
    win_rate: float = 0.0
    recent_win_rate: Optional[float] = None  # Last 30 trades
    historical_win_rate: Optional[float] = None  # All time
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: Optional[float] = None

    # Consecutive
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    current_streak: str = ""  # "W5" or "L3"

    # Heartbeat
    last_heartbeat: Optional[datetime] = None
    is_stale: bool = False
    hours_since_heartbeat: float = 0.0

    # Settings
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to plain dict for serialization."""
        d = asdict(self)
        if self.last_heartbeat:
            d["last_heartbeat"] = self.last_heartbeat.isoformat()
        return d

    @property
    def is_profitable(self) -> bool:
        return self.pnl > 0

    @property
    def health_score(self) -> float:
        """0-1 score: 1 = perfect health."""
        score = 1.0

        # WR penalty
        if self.win_rate < 0.30:
            score -= 0.3
        elif self.win_rate < 0.40:
            score -= 0.15

        # Profit factor penalty
        if self.profit_factor < 0.8:
            score -= 0.2
        elif self.profit_factor < 1.0:
            score -= 0.1

        # Stale penalty
        if self.is_stale:
            score -= 0.25

        # Drawdown penalty (if we have it)
        if self.max_drawdown > 100:
            score -= 0.1
        if self.max_drawdown > 500:
            score -= 0.2

        # Consecutive losses penalty
        if self.consecutive_losses >= 3:
            score -= 0.15
        if self.consecutive_losses >= 5:
            score -= 0.3

        return max(0.0, min(1.0, score))


class StrategyPerformanceTracker:
    """
    Fetches and analyzes strategy performance from all available sources.

    Sources consulted (in order):
    1. Trade table (realized PnL, win rate per strategy)
    2. StrategyConfig (enabled, params)
    3. BotState heartbeats (freshness)
    4. StrategyOutcome (evolution outcomes)
    """

    def __init__(self):
        pass

    async def fetch_all(
        self, modes: Optional[List[str]] = None
    ) -> Dict[str, StrategyReport]:
        """Fetch performance for ALL strategies across ALL active modes."""
        reports: Dict[str, StrategyReport] = {}
        active_modes = modes or list(settings.active_modes_set)

        for mode in active_modes:
            mode_reports = await self._fetch_for_mode(mode)
            for name, report in mode_reports.items():
                # If same strategy in multiple modes, append mode suffix
                key = f"{name}.{mode}" if name in reports else name
                reports[key] = report

        return reports

    async def fetch_strategy(
        self, strategy_name: str, mode: str = "paper"
    ) -> Optional[StrategyReport]:
        """Fetch performance for a single strategy."""
        reports = await self._fetch_for_mode(mode, strategy_names=[strategy_name])
        return reports.get(strategy_name)

    async def _fetch_for_mode(
        self,
        mode: str,
        strategy_names: Optional[List[str]] = None,
    ) -> Dict[str, StrategyReport]:
        """Fetch performance for all strategies in a given mode."""
        reports: Dict[str, StrategyReport] = {}

        try:
            with SessionLocal() as db:
                # ── Get strategy configs ──
                config_query = db.query(StrategyConfig)
                if strategy_names:
                    config_query = config_query.filter(
                        StrategyConfig.name.in_(strategy_names)
                    )
                if mode == "paper":
                    config_query = config_query.filter(StrategyConfig.mode == "paper")
                elif mode == "live":
                    config_query = config_query.filter(StrategyConfig.mode == "live")

                configs = config_query.all()
                {c.name: c for c in configs}

                # If no strategies found, return empty
                if not configs and not strategy_names:
                    return reports

                # ── Get heartbeats from BotState ──
                heartbeats = self._extract_heartbeats(db, mode)

                # ── For each strategy, build report ──
                for config in configs:
                    report = StrategyReport(
                        name=config.name,
                        mode=mode,
                        enabled=config.enabled,
                        params=config.params or {},
                    )

                    # Trade stats
                    trade_stats = self._compute_trade_stats(db, config.name, mode)
                    report.total_trades = trade_stats.get("total", 0)
                    report.pnl = trade_stats.get("pnl", 0.0)
                    report.pnl_7d = trade_stats.get("pnl_7d", 0.0)
                    report.pnl_30d = trade_stats.get("pnl_30d", 0.0)
                    report.win_rate = trade_stats.get("win_rate", 0.0)
                    report.profit_factor = trade_stats.get("profit_factor", 0.0)
                    report.avg_win = trade_stats.get("avg_win", 0.0)
                    report.avg_loss = trade_stats.get("avg_loss", 0.0)

                    # Consecutive stats
                    streak = self._compute_streaks(db, config.name, mode)
                    report.consecutive_wins = streak.get("wins", 0)
                    report.consecutive_losses = streak.get("losses", 0)
                    report.current_streak = streak.get("streak_str", "")

                    # Recent vs historical WR
                    wr_data = self._compute_wr_comparison(db, config.name, mode)
                    report.recent_win_rate = wr_data.get("recent_wr")
                    report.historical_win_rate = wr_data.get("historical_wr")

                    # Heartbeat
                    hb = heartbeats.get(config.name)
                    if hb:
                        report.last_heartbeat = hb
                        hours_ago = (
                            datetime.now(timezone.utc) - hb
                        ).total_seconds() / 3600
                        report.hours_since_heartbeat = hours_ago
                        report.is_stale = hours_ago > 0.25  # 15 min = stale
                    else:
                        report.is_stale = True
                        report.hours_since_heartbeat = 99.0

                    # Status determination
                    report.status = self._determine_status(report)

                    # Recent trades count
                    now = datetime.now(timezone.utc)
                    report.recent_trades_7d = db.query(Trade).filter(
                        Trade.strategy == config.name,
                        Trade.mode == mode,
                        Trade.timestamp >= now - timedelta(days=7),
                    ).count()
                    report.recent_trades_30d = db.query(Trade).filter(
                        Trade.strategy == config.name,
                        Trade.mode == mode,
                        Trade.timestamp >= now - timedelta(days=30),
                    ).count()

                    reports[config.name] = report

        except Exception as exc:
            logger.opt(exception=True).error(
                f"[StrategyTracker] Failed to fetch for mode={mode}: {exc}"
            )

        return reports

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _compute_trade_stats(
        self, db, strategy_name: str, mode: str
    ) -> Dict[str, float]:
        """Compute trade statistics from the Trade table."""
        stats: Dict[str, float] = {
            "total": 0,
            "pnl": 0.0,
            "pnl_7d": 0.0,
            "pnl_30d": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }

        try:
            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.mode == mode,
                    Trade.settled == True,  # noqa: E712
                )
                .all()
            )

            if not trades:
                return stats

            stats["total"] = len(trades)
            total_pnl = sum(t.pnl or 0.0 for t in trades)
            stats["pnl"] = total_pnl

            now = datetime.now(timezone.utc)
            wins = [t for t in trades if (t.pnl or 0.0) > 0]
            losses = [t for t in trades if (t.pnl or 0.0) <= 0]

            # Win rate
            stats["win_rate"] = len(wins) / len(trades) if trades else 0.0

            # Profit factor
            gross_win = sum(t.pnl or 0.0 for t in wins)
            gross_loss = abs(sum(t.pnl or 0.0 for t in losses))
            stats["profit_factor"] = (
                gross_win / gross_loss if gross_loss > 0 else 999.0
            )

            # Avgs
            stats["avg_win"] = gross_win / len(wins) if wins else 0.0
            stats["avg_loss"] = gross_loss / len(losses) if losses else 0.0

            # Time-bounded PnL
            for t in trades:
                ts = t.timestamp
                if ts and ts >= now - timedelta(days=7):
                    stats["pnl_7d"] += t.pnl or 0.0
                if ts and ts >= now - timedelta(days=30):
                    stats["pnl_30d"] += t.pnl or 0.0

        except Exception as exc:
            logger.debug(f"[StrategyTracker] Trade stats error: {exc}")

        return stats

    def _compute_streaks(
        self, db, strategy_name: str, mode: str
    ) -> Dict[str, Any]:
        """Compute current win/loss streaks from recent trades."""
        result = {"wins": 0, "losses": 0, "streak_str": ""}

        try:
            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.mode == mode,
                    Trade.settled == True,  # noqa: E712
                )
                .order_by(Trade.timestamp.desc())
                .limit(50)
                .all()
            )

            if not trades:
                return result

            streak_type = None
            streak_count = 0

            for t in trades:
                is_win = (t.pnl or 0.0) > 0
                if streak_type is None:
                    streak_type = "W" if is_win else "L"
                    streak_count = 1
                elif (is_win and streak_type == "W") or (not is_win and streak_type == "L"):
                    streak_count += 1
                else:
                    break

            result["wins"] = streak_count if streak_type == "W" else 0
            result["losses"] = streak_count if streak_type == "L" else 0
            result["streak_str"] = f"{streak_type}{streak_count}"

        except Exception as exc:
            logger.debug(f"[StrategyTracker] Streaks error: {exc}")

        return result

    def _compute_wr_comparison(
        self, db, strategy_name: str, mode: str
    ) -> Dict[str, Optional[float]]:
        """Compare recent win rate vs historical win rate."""
        result: Dict[str, Optional[float]] = {
            "recent_wr": None,
            "historical_wr": None,
        }

        try:
            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.mode == mode,
                    Trade.settled == True,  # noqa: E712
                )
                .order_by(Trade.timestamp.desc())
                .all()
            )

            if not trades:
                return result

            # Historical: all trades
            hist_wins = sum(1 for t in trades if (t.pnl or 0.0) > 0)
            result["historical_wr"] = hist_wins / len(trades) if trades else 0.0

            # Recent: last 30 trades
            recent = trades[:30]
            if len(recent) >= 10:
                recent_wins = sum(1 for t in recent if (t.pnl or 0.0) > 0)
                result["recent_wr"] = recent_wins / len(recent)

        except Exception as exc:
            logger.debug(f"[StrategyTracker] WR comparison error: {exc}")

        return result

    def _extract_heartbeats(self, db, mode: str) -> Dict[str, datetime]:
        """Extract strategy heartbeats from BotState."""
        heartbeats: Dict[str, datetime] = {}

        try:
            state = (
                db.query(BotState)
                .filter(BotState.mode == mode)
                .order_by(BotState.updated_at.desc())
                .first()
            )

            if state and state.misc_data:
                data = state.misc_data
                if isinstance(data, str):
                    data = json.loads(data)

                for key, val in data.items():
                    if key.startswith("heartbeat:"):
                        strategy_name = key.replace("heartbeat:", "")
                        if isinstance(val, str):
                            try:
                                heartbeats[strategy_name] = datetime.fromisoformat(val)
                            except (ValueError, TypeError):
                                pass
        except Exception as exc:
            logger.debug(f"[StrategyTracker] Heartbeat extraction error: {exc}")

        return heartbeats

    def _determine_status(self, report: StrategyReport) -> str:
        """Determine health status from report data."""
        if not report.enabled:
            return "disabled"
        if report.is_stale:
            return "warning"
        if report.health_score < 0.3:
            return "critical"
        if report.health_score < 0.6:
            return "warning"
        if report.total_trades == 0:
            return "inactive"
        return "healthy" if report.health_score >= 0.6 else "warning"
