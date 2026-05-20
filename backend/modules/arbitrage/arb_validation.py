"""Resolution source validation for cross-platform arbitrage safety."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ResolutionComparison:
    source_match: bool
    settlement_time_delta_hours: float
    dispute_process_match: bool
    risk_score: float


def compare_resolution(market_a: dict, market_b: dict) -> ResolutionComparison:
    source_match = market_a.get("resolution_source") == market_b.get(
        "resolution_source"
    )

    try:
        time_a = datetime.fromisoformat(market_a.get("end_date", ""))
        time_b = datetime.fromisoformat(market_b.get("end_date", ""))
        time_delta = abs((time_a - time_b).total_seconds()) / 3600
    except (ValueError, TypeError):
        time_delta = 24.0

    dispute_process_match = (
        market_a.get("dispute_process") == market_b.get("dispute_process")
        if "dispute_process" in market_a and "dispute_process" in market_b
        else True
    )

    risk = (0.0 if source_match else 0.5) + min(0.5, time_delta / 24)
    if not dispute_process_match:
        risk += 0.2
    risk = min(1.0, risk)

    return ResolutionComparison(
        source_match=source_match,
        settlement_time_delta_hours=time_delta,
        dispute_process_match=dispute_process_match,
        risk_score=risk,
    )


def is_safe_arb(market_a: dict, market_b: dict, max_risk: float = 0.3) -> bool:
    comparison = compare_resolution(market_a, market_b)
    return comparison.risk_score <= max_risk
