"""CopySource ABC and supporting dataclasses for the copy-trade subsystem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CopyPolicyConfig:
    """Runtime policy configuration for a copy signal source."""

    source_name: str
    enabled: bool
    max_size_usd: float
    confidence_floor: float
    max_delay_seconds: int
    size_scale_factor: float
    cooldown_seconds: int


@dataclass
class CopySignalData:
    """A single copy-trade signal captured from a source."""

    source_name: str
    leader_address: str
    condition_id: str
    side: str  # "YES" | "NO"
    raw_size: float
    confidence: float
    captured_at: datetime
    metadata: dict = field(default_factory=dict)


class CopySource(ABC):
    """Abstract base for pluggable copy-trade signal sources.

    Implementations must provide:
    - ``get_name``: unique source identifier
    - ``fetch_signals``: return pending copy signals
    - ``is_healthy``: liveness check (e.g. API reachable, data fresh)
    """

    @abstractmethod
    def get_name(self) -> str:
        """Return the unique name of this copy source."""

    @abstractmethod
    async def fetch_signals(self) -> list[CopySignalData]:
        """Fetch pending copy signals from the source."""

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Return True if the source is reachable and data is fresh."""
