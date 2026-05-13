

from backend.backtesting.base import (
    BacktestDataSourceManifest,
    BaseBacktestDataSource,
    BacktestStrategyRunnerManifest,
    BaseBacktestStrategyRunner,
    BacktestMetricsManifest,
    BaseBacktestMetrics,
)
from backend.backtesting.registry import (
    BacktestEngineRegistry,
    get_registry,
    reset_registry,
)
from backend.strategies.registry import STRATEGY_REGISTRY


class MockDataSource(BaseBacktestDataSource):
    def __init__(self) -> None:
        self.manifest = BacktestDataSourceManifest(
            name="mock",
            display_name="Mock Data Source",
            version="1.0.0",
            supported_markets=["test"],
            tags=["mock"],
        )

    def load_data(self, market_ticker: str, start_date: str, end_date: str) -> object:
        import pandas as pd

        mock_data = pd.DataFrame(
            {
                "timestamp": ["2024-01-01", "2024-01-02"],
                "price": [100.0, 101.0],
                "volume": [1000, 2000],
            }
        )
        return mock_data

    def health_check(self) -> bool:
        return True


class MockStrategyRunner(BaseBacktestStrategyRunner):
    def __init__(self) -> None:
        self.manifest = BacktestStrategyRunnerManifest(
            name="mock",
            display_name="Mock Strategy Runner",
            version="1.0.0",
            description="Mock runner for testing",
            tags=["mock"],
        )

    def run_strategy(
        self,
        strategy_cls: type,
        data: object,
        params: dict,
    ) -> list[dict]:
        return [
            {
                "timestamp": "2024-01-01",
                "pnl": 100.0,
                "side": "long",
            },
            {
                "timestamp": "2024-01-02",
                "pnl": -50.0,
                "side": "short",
            },
        ]

    def health_check(self) -> bool:
        return True


class MockMetrics(BaseBacktestMetrics):
    def __init__(self) -> None:
        self.manifest = BacktestMetricsManifest(
            name="mock",
            display_name="Mock Metrics",
            version="1.0.0",
            description="Mock metrics for testing",
            tags=["mock"],
        )

    def compute(self, trades: list[dict], equity_curve: list[dict]) -> dict:
        return {
            "custom_metric": 42.0,
            "trade_count": len(trades),
        }

    def health_check(self) -> bool:
        return True


class MockStrategy:
    name = "mock"
    backtest_mode = False
    description = "Mock strategy for testing"
    category = "test"

    def __init__(self, backtest_mode: bool = False, **kwargs) -> None:
        self.backtest_mode = backtest_mode


STRATEGY_REGISTRY["mock"] = MockStrategy


def test_register_data_source():
    registry = BacktestEngineRegistry()
    data_source = MockDataSource()
    registry.register_data_source("mock_data", data_source)

    assert registry.has_data_source("mock_data")
    assert registry.get_data_source("mock_data") == data_source


def test_register_strategy_runner():
    registry = BacktestEngineRegistry()
    runner = MockStrategyRunner()
    registry.register_strategy_runner("mock_runner", runner)

    assert registry.has_strategy_runner("mock_runner")
    assert registry.get_strategy_runner("mock_runner") == runner


def test_register_metrics():
    registry = BacktestEngineRegistry()
    metrics = MockMetrics()
    registry.register_metrics("mock_metrics", metrics)

    assert registry.has_metrics("mock_metrics")
    assert registry.get_metrics("mock_metrics") == metrics


def test_run_backtest():
    registry = BacktestEngineRegistry()
    registry.register_data_source("mock", MockDataSource())
    registry.register_strategy_runner("mock", MockStrategyRunner())
    registry.register_metrics("mock", MockMetrics())

    result = registry.run_backtest(
        strategy_name="mock",
        market_ticker="BTC-USD",
        start_date="2024-01-01",
        end_date="2024-01-31",
        params={},
        data_source_key="mock",
        strategy_runner_key="mock",
        metrics_key="mock",
    )

    assert "trades" in result
    assert "equity_curve" in result
    assert "metrics" in result
    assert len(result["trades"]) == 2


def test_run_backtest_full_integration():

    registry = BacktestEngineRegistry()

    mock_data_source = MockDataSource()
    registry.register_data_source("polymarket", mock_data_source)

    mock_runner = MockStrategyRunner()
    registry.register_strategy_runner("default", mock_runner)

    mock_metrics = MockMetrics()
    registry.register_metrics("sharpe", mock_metrics)

    result = registry.run_backtest(
        strategy_name="mock",
        market_ticker="BTC-USD",
        start_date="2024-01-01",
        end_date="2024-01-31",
        params={},
        data_source_key="polymarket",
        strategy_runner_key="default",
        metrics_key="sharpe",
    )

    assert "trades" in result
    assert "equity_curve" in result
    assert "metrics" in result
    assert "trade_count" in result["metrics"]
    assert result["metrics"]["trade_count"] == 2


def test_reset_registry():
    registry = BacktestEngineRegistry()
    registry.register_data_source("test", MockDataSource())
    registry.register_strategy_runner("test", MockStrategyRunner())
    registry.register_metrics("test", MockMetrics())

    assert registry.has_data_source("test")
    assert registry.has_strategy_runner("test")
    assert registry.has_metrics("test")

    registry.reset()

    assert not registry.has_data_source("test")
    assert not registry.has_strategy_runner("test")
    assert not registry.has_metrics("test")


def test_reset_function():
    registry = get_registry()
    registry.register_data_source("test", MockDataSource())
    registry.register_strategy_runner("test", MockStrategyRunner())
    registry.register_metrics("test", MockMetrics())

    assert registry.has_data_source("test")

    reset_registry()

    registry = get_registry()
    assert not registry.has_data_source("test")
