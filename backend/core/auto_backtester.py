"""Auto-backtester — automatically re-backtest when new data arrives.

Triggers backtesting when new HuggingFace dataset data is downloaded
or new market data becomes available. Compares current strategy
performance vs historical baseline and alerts on degradation.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

DEFAULT_BACKTEST_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "models", "backtest_state.json"
)


@dataclass
class BacktestSnapshot:
    """A snapshot of strategy performance from a backtest run."""
    timestamp: float
    strategy_name: str
    win_rate: float
    roi: float
    sharpe_ratio: float
    total_trades: int
    max_drawdown: float
    pnl: float


@dataclass
class DegradationAlert:
    """Alert when backtest shows performance degradation."""
    strategy_name: str
    metric: str
    current_value: float
    baseline_value: float
    degradation_pct: float
    timestamp: float = field(default_factory=time.time)


class AutoBacktester:
    """Automatically re-backtests strategies when new data arrives."""

    def __init__(
        self,
        state_path: Optional[str] = None,
        degradation_threshold_pct: float = 10.0,
        min_trades_for_comparison: int = 10,
    ):
        self.state_path = state_path or DEFAULT_BACKTEST_STATE_PATH
        self.degradation_threshold = degradation_threshold_pct / 100
        self.min_trades = min_trades_for_comparison
        self._baselines: Dict[str, BacktestSnapshot] = {}
        self._history: List[BacktestSnapshot] = []
        self._alerts: List[DegradationAlert] = []
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted backtest state."""
        import json
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            for name, snap_data in data.get("baselines", {}).items():
                self._baselines[name] = BacktestSnapshot(**snap_data)
            for snap_data in data.get("history", []):
                self._history.append(BacktestSnapshot(**snap_data))
            logger.info(f"auto_backtester: loaded {len(self._baselines)} baselines")
        except Exception as e:
            logger.warning(f"auto_backtester: failed to load state: {e}")

    def _save_state(self) -> None:
        """Persist backtest state to disk."""
        import json
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        data = {
            "baselines": {
                name: {
                    "timestamp": s.timestamp,
                    "strategy_name": s.strategy_name,
                    "win_rate": s.win_rate,
                    "roi": s.roi,
                    "sharpe_ratio": s.sharpe_ratio,
                    "total_trades": s.total_trades,
                    "max_drawdown": s.max_drawdown,
                    "pnl": s.pnl,
                }
                for name, s in self._baselines.items()
            },
            "history": [
                {
                    "timestamp": s.timestamp,
                    "strategy_name": s.strategy_name,
                    "win_rate": s.win_rate,
                    "roi": s.roi,
                    "sharpe_ratio": s.sharpe_ratio,
                    "total_trades": s.total_trades,
                    "max_drawdown": s.max_drawdown,
                    "pnl": s.pnl,
                }
                for s in self._history[-100:]  # keep last 100
            ],
        }
        try:
            with open(self.state_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"auto_backtester: failed to save state: {e}")

    async def on_new_data(self, source: str = "unknown") -> List[DegradationAlert]:
        """Trigger backtest when new data arrives.

        Args:
            source: Description of data source (e.g., "hf_dataset", "market_data")

        Returns:
            List of degradation alerts if any strategy performance declined.
        """
        logger.info(f"auto_backtester: triggered by new data from {source}")
        snapshots = await self._run_backtests()
        alerts = []
        for snap in snapshots:
            self._history.append(snap)
            alert = self._check_degradation(snap)
            if alert:
                alerts.append(alert)
                self._alerts.append(alert)
            # Update baseline if improved
            self._update_baseline(snap)
        self._save_state()
        return alerts

    async def _run_backtests(self) -> List[BacktestSnapshot]:
        """Run backtests for active strategies."""
        snapshots = []
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import Trade, StrategyConfig

            with get_db_session() as db:
                strategies = db.query(StrategyConfig).filter(
                    StrategyConfig.enabled.is_(True)
                ).all()

                for strat in strategies:
                    trades = db.query(Trade).filter(
                        Trade.strategy_name == strat.name,
                        Trade.settled.is_(True),
                    ).all()

                    if len(trades) < self.min_trades:
                        continue

                    wins = sum(1 for t in trades if (t.pnl or 0) > 0)
                    total_pnl = sum(t.pnl or 0 for t in trades)
                    roi = total_pnl / max(sum(abs(t.size or 0) for t in trades), 1)

                    snap = BacktestSnapshot(
                        timestamp=time.time(),
                        strategy_name=strat.name,
                        win_rate=wins / len(trades) if trades else 0,
                        roi=roi,
                        sharpe_ratio=0.0,  # simplified
                        total_trades=len(trades),
                        max_drawdown=0.0,
                        pnl=total_pnl,
                    )
                    snapshots.append(snap)
        except Exception as e:
            logger.warning(f"auto_backtester: backtest failed: {e}")
        return snapshots

    def _check_degradation(self, snap: BacktestSnapshot) -> Optional[DegradationAlert]:
        """Check if a strategy's performance has degraded."""
        baseline = self._baselines.get(snap.strategy_name)
        if not baseline:
            return None

        # Check win rate degradation
        if baseline.win_rate > 0:
            wr_decline = (baseline.win_rate - snap.win_rate) / baseline.win_rate
            if wr_decline > self.degradation_threshold:
                return DegradationAlert(
                    strategy_name=snap.strategy_name,
                    metric="win_rate",
                    current_value=snap.win_rate,
                    baseline_value=baseline.win_rate,
                    degradation_pct=wr_decline,
                )

        # Check ROI degradation
        if baseline.roi > 0:
            roi_decline = (baseline.roi - snap.roi) / abs(baseline.roi)
            if roi_decline > self.degradation_threshold:
                return DegradationAlert(
                    strategy_name=snap.strategy_name,
                    metric="roi",
                    current_value=snap.roi,
                    baseline_value=baseline.roi,
                    degradation_pct=roi_decline,
                )

        return None

    def _update_baseline(self, snap: BacktestSnapshot) -> None:
        """Update baseline if performance improved."""
        baseline = self._baselines.get(snap.strategy_name)
        if not baseline:
            self._baselines[snap.strategy_name] = snap
            return

        # Update if win rate improved and has enough trades
        if snap.win_rate >= baseline.win_rate and snap.total_trades >= self.min_trades:
            self._baselines[snap.strategy_name] = snap

    @property
    def baselines(self) -> Dict[str, BacktestSnapshot]:
        return self._baselines.copy()

    @property
    def recent_alerts(self) -> List[DegradationAlert]:
        return self._alerts[-20:]

    def get_stats(self) -> Dict[str, Any]:
        """Return backtester statistics."""
        return {
            "baselines_count": len(self._baselines),
            "history_count": len(self._history),
            "total_alerts": len(self._alerts),
            "strategies_tracked": list(self._baselines.keys()),
        }
