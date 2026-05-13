"""Metrics backend plugin system for PolyEdge monitoring."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class MetricsBackendManifest:
    name: str
    display_name: str
    version: str
    required_env_vars: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class BaseMetricsBackend(ABC):
    @classmethod
    @abstractmethod
    def manifest(cls) -> MetricsBackendManifest:
        ...

    @abstractmethod
    async def increment_counter(self, name: str, value: int = 1, tags: dict = None) -> None:
        ...

    @abstractmethod
    async def record_gauge(self, name: str, value: float, tags: dict = None) -> None:
        ...

    @abstractmethod
    async def record_histogram(self, name: str, value: float, tags: dict = None) -> None:
        ...

    async def health_check(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass
