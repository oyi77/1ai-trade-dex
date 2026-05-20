"""HFT Strategy Types — typed signals, executions, and configs for HFT strategies."""

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional
from datetime import datetime, timezone
import json
import uuid


@dataclass
class HFTSignal:
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    market_id: str = ""
    ticker: str = ""
    signal_type: Literal["edge", "arb", "cross_arb", "whale", "prob_arb"] = "edge"
    edge: float = 0.0
    confidence: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HFTSignal":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> "HFTSignal":
        return cls.from_dict(json.loads(s))

    def validate(self) -> bool:
        if not self.signal_id:
            return False
        if not (0.0 <= self.confidence <= 1.0):
            return False
        if not (0.0 <= self.edge <= 1.0):
            return False
        return True


@dataclass
class HFTExecution:
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str = ""
    order_id: Optional[str] = None
    side: Literal["BUY", "SELL"] = "BUY"
    size: float = 0.0
    price: float = 0.0
    execution_latency_ms: float = 0.0
    status: Literal["pending", "filled", "failed", "queued", "cancelled"] = "pending"
    error: Optional[str] = None
    timestamp: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HFTExecution":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> "HFTExecution":
        return cls.from_dict(json.loads(s))


@dataclass
class HFTStrategyConfig:
    name: str = ""
    enabled: bool = False
    min_edge: float = 0.02
    min_volume: float = 1000.0
    max_position: float = 100.0
    auto_execute: bool = True
    max_latency_ms: float = 100.0
    scan_interval_ms: float = 1000.0
    position_size_pct: float = 0.25

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HFTStrategyConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

    def validate(self) -> bool:
        if not self.name:
            return False
        if not (0.0 <= self.position_size_pct <= 1.0):
            return False
        if not (0.0 <= self.min_edge <= 1.0):
            return False
        return True


@dataclass
class WhaleActivity:
    wallet: str
    action: Literal["BUY", "SELL"]
    size: float
    market: str
    score: float
    timestamp: float
    tx_hash: Optional[str] = None

    def is_whale(self, min_size: float = 10000.0, min_score: float = 0.8) -> bool:
        return self.size >= min_size and self.score >= min_score


@dataclass
class ArbOpportunity:
    opportunity_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    market_id: str = ""
    arb_type: Literal["prob_arb", "cross_arb", "negrisk"] = "prob_arb"
    yes_price: float = 0.0
    no_price: float = 0.0
    sum_price: float = 0.0
    profit: float = 0.0
    fees: float = 0.0
    net_profit: float = 0.0
    confidence: float = 0.0
    timestamp: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ArbOpportunity":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})
