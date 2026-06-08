from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class TradeMetrics:
    timestamp: datetime
    action: str
    token: str
    price: float
    amount_usdc: float
    amount_token: float
    pnl_usdc: float
    reason: str
    sma_fast: Optional[float] = None
    sma_slow: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "token": self.token,
            "price": round(self.price, 2),
            "amount_usdc": round(self.amount_usdc, 2),
            "amount_token": round(self.amount_token, 6),
            "pnl_usdc": round(self.pnl_usdc, 2),
            "reason": self.reason,
            "sma_fast": round(self.sma_fast, 2) if self.sma_fast else None,
            "sma_slow": round(self.sma_slow, 2) if self.sma_slow else None,
        }


@dataclass
class BotMetrics:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_pnl_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    win_rate_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    in_position: bool = False
    in_cooldown: bool = False
    health: str = "healthy"
    trades: List[TradeMetrics] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "pnl": {
                "total_usd": round(self.total_pnl_usd, 2),
                "daily_usd": round(self.daily_pnl_usd, 2),
            },
            "trading": {
                "trades_today": self.trades_today,
                "consecutive_losses": self.consecutive_losses,
                "in_position": self.in_position,
                "in_cooldown": self.in_cooldown,
            },
            "analytics": {
                "win_rate_pct": round(self.win_rate_pct, 2),
                "max_drawdown_pct": round(self.max_drawdown_pct, 2),
                "sharpe_ratio": round(self.sharpe_ratio, 3),
            },
            "health": self.health,
        }


class MetricsCollector:
    def __init__(self):
        self._trades: List[TradeMetrics] = []
        self._equity: List[float] = [34.0]
        self._win_count = 0
        self._loss_count = 0

    def record_trade(self, trade: TradeMetrics):
        self._trades.append(trade)
        logger.info("Trade recorded: {} {} @ ${}", trade.action, trade.token, trade.price)
        if trade.pnl_usdc > 0:
            self._win_count += 1
        elif trade.pnl_usdc < 0:
            self._loss_count += 1

    def update_equity(self, total_pnl_usd: float):
        self._equity.append(34.0 + total_pnl_usd)

    def get_stats(self) -> Dict:
        total_trades = len(self._trades)
        if total_trades == 0:
            return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_pnl": 0.0}

        wins = self._win_count
        losses = self._loss_count
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        avg_pnl = sum(t.pnl_usdc for t in self._trades) / total_trades

        return {
            "trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "avg_pnl": round(avg_pnl, 2),
        }

    def get_drawdown(self) -> float:
        if not self._equity:
            return 0.0
        peak = max(self._equity)
        trough = min(self._equity)
        return ((peak - trough) / peak * 100) if peak > 0 else 0.0

    def get_sharpe(self, risk_free_rate: float = 0.0) -> float:
        if len(self._equity) < 2:
            return 0.0
        returns = [
            ((self._equity[i] - self._equity[i - 1]) / self._equity[i - 1]) * 100
            for i in range(1, len(self._equity))
        ]
        if not returns:
            return 0.0
        avg_return = sum(returns) / len(returns)
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5
        if std_dev == 0:
            return 0.0
        return ((avg_return - risk_free_rate) / std_dev) if std_dev > 0 else 0.0

    def get_metrics(self, total_pnl: float, daily_pnl: float, trades_today: int,
                    consecutive_losses: int, in_position: bool, in_cooldown: bool) -> BotMetrics:
        stats = self.get_stats()
        return BotMetrics(
            total_pnl_usd=total_pnl,
            daily_pnl_usd=daily_pnl,
            trades_today=trades_today,
            consecutive_losses=consecutive_losses,
            win_rate_pct=stats.get("win_rate", 0.0),
            max_drawdown_pct=self.get_drawdown(),
            sharpe_ratio=self.get_sharpe(),
            in_position=in_position,
            in_cooldown=in_cooldown,
            trades=self._trades[-20:],
            equity_curve=self._equity[-100:],
            health="healthy" if not in_cooldown else "caution",
        )
