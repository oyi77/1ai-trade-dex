"""Shared dataclasses for AGI evaluation benchmarks."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict


@dataclass
class BenchmarkResult:
    """Standard result container for all AGI benchmarks."""
    benchmark_id: str
    score: float
    passed: bool
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
