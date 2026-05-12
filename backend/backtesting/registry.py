from typing import Any

from backend.backtesting.base import (
    BaseBacktestDataSource,
    BaseBacktestMetrics,
    BaseBacktestStrategyRunner,
)


class BacktestEngineRegistry:
    def __init__(self) -> None:
        self._data_sources: dict[str, BaseBacktestDataSource] = {}
        self._strategy_runners: dict[str, BaseBacktestStrategyRunner] = {}
        self._metrics: dict[str, BaseBacktestMetrics] = {}

    def register_data_source(
        self,
        key: str,
        instance: BaseBacktestDataSource,
    ) -> None:
        self._data_sources[key] = instance

    def register_strategy_runner(
        self,
        key: str,
        instance: BaseBacktestStrategyRunner,
    ) -> None:
        self._strategy_runners[key] = instance

    def register_metrics(
        self,
        key: str,
        instance: BaseBacktestMetrics,
    ) -> None:
        self._metrics[key] = instance

    def get_data_source(self, key: str) -> BaseBacktestDataSource:
        return self._data_sources[key]

    def get_strategy_runner(self, key: str) -> BaseBacktestStrategyRunner:
        return self._strategy_runners[key]

    def get_metrics(self, key: str) -> BaseBacktestMetrics:
        return self._metrics[key]

    def has_data_source(self, key: str) -> bool:
        return key in self._data_sources

    def has_strategy_runner(self, key: str) -> bool:
        return key in self._strategy_runners

    def has_metrics(self, key: str) -> bool:
        return key in self._metrics

    def run_backtest(
        self,
        strategy_name: str,
        market_ticker: str,
        start_date: str,
        end_date: str,
        params: dict[str, Any],
        data_source_key: str = "polymarket",
        strategy_runner_key: str = "default",
        metrics_key: str = "sharpe",
    ) -> dict[str, Any]:
        data_source = self.get_data_source(data_source_key)
        strategy_runner = self.get_strategy_runner(strategy_runner_key)
        metrics_calculator = self.get_metrics(metrics_key)

        data = data_source.load_data(market_ticker, start_date, end_date)

        trades = strategy_runner.run_strategy(
            strategy_cls=self._get_strategy_class(strategy_name),
            data=data,
            params=params,
        )

        equity_curve = self._compute_equity_curve(trades)

        metrics = metrics_calculator.compute(trades, equity_curve)

        return {
            "trades": trades,
            "equity_curve": equity_curve,
            "metrics": metrics,
        }

    def _get_strategy_class(self, strategy_name: str) -> type:
        from backend.strategies.registry import get_strategy_class

        return get_strategy_class(strategy_name)

    def _compute_equity_curve(self, trades: list[dict]) -> list[dict]:
        equity = 10000.0
        equity_curve = []
        for trade in trades:
            pnl = trade.get("pnl", 0.0)
            equity += pnl
            equity_curve.append(
                {
                    "timestamp": trade.get("timestamp"),
                    "equity": equity,
                    "pnl": pnl,
                }
            )
        return equity_curve

    def reset(self) -> None:
        self._data_sources.clear()
        self._strategy_runners.clear()
        self._metrics.clear()


_registry = BacktestEngineRegistry()


def get_registry() -> BacktestEngineRegistry:
    return _registry


def reset_registry() -> None:
    _registry.reset()
