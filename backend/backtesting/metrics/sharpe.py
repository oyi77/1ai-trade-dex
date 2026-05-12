from backend.backtesting.base import (
    BacktestMetricsManifest,
    BaseBacktestMetrics,
)


class SharpeRatioMetrics(BaseBacktestMetrics):
    def __init__(self) -> None:
        self.manifest = BacktestMetricsManifest(
            name="sharpe",
            display_name="Sharpe Ratio Metrics",
            version="1.0.0",
            description="Risk-adjusted return metrics including Sharpe ratio, Sortino ratio, and max drawdown",
            tags=["risk-adjusted", "performance", "volatility"],
        )

    def compute(self, trades: list[dict], equity_curve: list[dict]) -> dict:
        if not trades:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown": 0.0,
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
            }

        pnl_values = [t.get("pnl", 0.0) for t in trades]
        total_pnl = sum(pnl_values)

        returns = []
        for i, trade in enumerate(trades):
            equity_before = equity_curve[i]["equity"] - trade.get("pnl", 0.0)
            if equity_before > 0:
                return_pct = trade.get("pnl", 0.0) / equity_before
                returns.append(return_pct)

        if not returns:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown": 0.0,
                "total_trades": len(trades),
                "win_rate": 0.0,
                "total_pnl": total_pnl,
            }

        import numpy as np

        returns_array = np.array(returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array)

        if std_return == 0:
            sharpe_ratio = 0.0
        else:
            sharpe_ratio = mean_return / std_return

        negative_returns = returns_array[returns_array < 0]
        if len(negative_returns) > 0:
            std_negative = np.std(negative_returns)
            if std_negative == 0:
                sortino_ratio = 0.0
            else:
                sortino_ratio = mean_return / std_negative
        else:
            sortino_ratio = float("inf")

        max_drawdown = self._calculate_max_drawdown(equity_curve)

        winning_trades = sum(1 for t in trades if t.get("pnl", 0) > 0)
        win_rate = winning_trades / len(trades) if trades else 0.0

        return {
            "sharpe_ratio": round(sharpe_ratio, 4),
            "sortino_ratio": round(sortino_ratio, 4),
            "max_drawdown": round(max_drawdown, 4),
            "total_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 2),
        }

    def _calculate_max_drawdown(self, equity_curve: list[dict]) -> float:
        if not equity_curve:
            return 0.0

        max_equity = equity_curve[0]["equity"]
        max_dd = 0.0

        for entry in equity_curve:
            current_equity = entry["equity"]
            if current_equity > max_equity:
                max_equity = current_equity
            elif current_equity < max_equity:
                drawdown = (max_equity - current_equity) / max_equity
                max_dd = max(max_dd, drawdown)

        return max_dd

    def health_check(self) -> bool:
        try:
            import numpy as np

            del np
            return True
        except Exception:
            return False
