from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class BacktestDataSourceManifest:
    name: str
    display_name: str
    version: str
    supported_markets: list[str]
    tags: list[str]


class BaseBacktestDataSource(ABC):
    @abstractmethod
    def load_data(self, market_ticker: str, start_date: str, end_date: str) -> Any:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass


@dataclass
class BacktestStrategyRunnerManifest:
    name: str
    display_name: str
    version: str
    description: str
    tags: list[str]


class BaseBacktestStrategyRunner(ABC):
    @abstractmethod
    def run_strategy(
        self,
        strategy_cls: type,
        data: Any,
        params: dict[str, Any],
    ) -> list[dict]:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass


@dataclass
class BacktestMetricsManifest:
    name: str
    display_name: str
    version: str
    description: str
    tags: list[str]


class BaseBacktestMetrics(ABC):
    @abstractmethod
    def compute(self, trades: list[dict], equity_curve: list[dict]) -> dict:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass


__all__ = [
    "BacktestDataSourceManifest",
    "BaseBacktestDataSource",
    "BacktestStrategyRunnerManifest",
    "BaseBacktestStrategyRunner",
    "BacktestMetricsManifest",
    "BaseBacktestMetrics",
]
