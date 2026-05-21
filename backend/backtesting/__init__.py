from backend.backtesting.base import (
    BacktestDataSourceManifest,
    BaseBacktestDataSource,
    BacktestMetricsManifest,
    BaseBacktestMetrics,
    BacktestStrategyRunnerManifest,
    BaseBacktestStrategyRunner,
)
from backend.backtesting.registry import (
    BacktestEngineRegistry,
    get_registry,
    reset_registry,
)


def setup_registry() -> BacktestEngineRegistry:
    """Register default data sources, strategy runners, and metrics."""
    registry = get_registry()
    from backend.backtesting.data_sources.polymarket import PolymarketBacktestDataSource
    from backend.backtesting.strategy_runners.default import DefaultStrategyRunner
    from backend.backtesting.metrics.sharpe import SharpeRatioMetrics

    if not registry.has_data_source("polymarket"):
        registry.register_data_source("polymarket", PolymarketBacktestDataSource())
    if not registry.has_strategy_runner("default"):
        registry.register_strategy_runner("default", DefaultStrategyRunner())
    if not registry.has_metrics("sharpe"):
        registry.register_metrics("sharpe", SharpeRatioMetrics())
    return registry


__all__ = [
    "BacktestDataSourceManifest",
    "BaseBacktestDataSource",
    "BacktestStrategyRunnerManifest",
    "BaseBacktestStrategyRunner",
    "BacktestMetricsManifest",
    "BaseBacktestMetrics",
    "BacktestEngineRegistry",
    "get_registry",
    "reset_registry",
    "setup_registry",
]
