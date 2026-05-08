"""DataSource ABC, Provenance, and core types for the DataMesh layer."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib


class SourceState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class Provenance:
    source_id: str
    raw_data_hash: str
    ingestion_timestamp: datetime
    schema_version: str
    transform_chain: List[str] = field(default_factory=list)
    confidence: float = 1.0

    @classmethod
    def from_raw(cls, source_id: str, raw_data: str, schema_version: str, confidence: float = 1.0) -> "Provenance":
        return cls(
            source_id=source_id,
            raw_data_hash=hashlib.sha256(raw_data.encode()).hexdigest()[:16],
            ingestion_timestamp=datetime.now(timezone.utc),
            schema_version=schema_version,
            confidence=confidence,
        )


@dataclass
class DataQuery:
    source_id: str = ""
    market: str = ""
    ticker: str = ""
    limit: int = 20
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RawPacket:
    source_id: str
    data: Any
    provenance: Provenance
    latency_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class HealthStatus:
    source_id: str
    state: SourceState
    success_rate: float = 1.0
    p95_latency_ms: float = 0.0
    staleness_seconds: float = 0.0
    consecutive_failures: int = 0
    last_check: Optional[datetime] = None


class DataSource(ABC):
    @property
    @abstractmethod
    def source_id(self) -> str: ...

    @property
    @abstractmethod
    def schema_version(self) -> str: ...

    @abstractmethod
    async def ingest(self, query: DataQuery) -> RawPacket: ...

    @abstractmethod
    async def health_check(self) -> HealthStatus: ...
