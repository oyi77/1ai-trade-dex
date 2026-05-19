"""Adapter wrapping backtesting.py's Backtest class with our strategy interface.

Provides a bridge between backtesting.py (the library) and PolyEdge's
BaseBacktestStrategyRunner, allowing strategies to be backtested using
the backtesting.py engine.

Usage:
    adapter = BacktestingPyAdapter()
    result = adapter.run_strategy(MyStrategy, ohlc_data, params={"period": 14})
"""

from typing import Any, Type

from loguru import logger

from backend.backtesting.base import (
    BaseBacktestStrategyRunner,
    BacktestStrategyRunnerManifest,
)


class BacktestingPyAdapter(BaseBacktestStrategyRunner):
    """Adapter that wraps backtesting.py's Backtest for PolyEdge strategies.

    This is a minimal scaffold. To use:
    1. Convert your market data to a pandas DataFrame with OHLCV columns
    2. Define a backtesting.py Strategy subclass that wraps your PolyEdge strategy
    3. Pass both to run_strategy()
    """

    manifest = BacktestStrategyRunnerManifest(
        name="backtesting_py",
        display_name="backtesting.py Adapter",
        version="0.1.0",
        description="Wraps backtesting.py Backtest engine for PolyEdge strategy backtesting",
        tags=["backtesting", "backtesting_py", "ohlcv"],
    )

    def run_strategy(
        self,
        strategy_cls: Type,
        data: Any,
        params: dict[str, Any],
    ) -> list[dict]:
        """Run a strategy through backtesting.py.

        Args:
            strategy_cls: PolyEdge strategy class (must be adaptable to backtesting.py).
            data: pandas DataFrame with OHLCV columns (Open, High, Low, Close, Volume).
            params: Strategy parameters to pass.

        Returns:
            List of trade dicts with keys: entry_time, exit_time, direction, pnl, etc.
        """
        try:
            from backtesting import Backtest
        except ImportError:
            logger.error("backtesting.py not installed. Install with: pip install backtesting.py")
            return []

        # Wrap the PolyEdge strategy as a backtesting.py Strategy
        bt_strategy = self._wrap_strategy(strategy_cls, params)

        try:
            bt = Backtest(
                data,
                bt_strategy,
                cash=params.get("cash", 10_000),
                commission=params.get("commission", 0.002),
                exclusive_orders=True,
            )
            stats = bt.run()

            # Convert backtesting.py trades to our format
            trades = []
            for _, row in stats._trades.iterrows():
                trades.append({
                    "entry_time": str(row.get("EntryBar", "")),
                    "exit_time": str(row.get("ExitBar", "")),
                    "direction": "long" if row.get("Size", 0) > 0 else "short",
                    "pnl": float(row.get("PnL", 0)),
                    "return_pct": float(row.get("ReturnPct", 0)),
                })

            return trades

        except Exception as e:
            logger.error("backtesting.py execution failed: {}", e)
            return []

    def _wrap_strategy(self, strategy_cls: Type, params: dict):
        """Create a backtesting.py Strategy that delegates to a PolyEdge strategy.

        This is a scaffold — actual implementation depends on the specific
        strategy interface being wrapped.
        """
        from backtesting import Strategy as BTStrategy

        class WrappedStrategy(BTStrategy):
            def init(self):
                self._poly_strategy = strategy_cls()
                self._params = params

            def next(self):
                # Scaffold: delegate to PolyEdge strategy's signal generation
                # Real implementation would map OHLCV data to market events
                pass

        return WrappedStrategy

    def health_check(self) -> bool:
        try:
# noqa: F401 - used via getattr            import backtesting
            return True
        except ImportError:
            return False
