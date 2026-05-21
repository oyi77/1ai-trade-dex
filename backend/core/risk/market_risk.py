"""DEPRECATED: Use backend.core.market_risk instead.

DEPRECATED: Use backend.core.market_risk instead.
This module will be removed in a future release.


This module will be removed in a future release.
"""

from dataclasses import dataclass
from enum import Enum


class RiskGrade(str, Enum):
    A = "A"  # 80-100
    B = "B"  # 60-79
    C = "C"  # 40-59
    D = "D"  # 20-39
    F = "F"  # 0-19


@dataclass
class MarketRiskGrade:
    grade: RiskGrade
    score: int  # 0-100
    factor_breakdown: dict[str, float]  # factor_name -> score 0-100
    warnings: list[str]


class MarketRiskGrader:
    """Grades markets on a 6-factor weighted scale."""

    FACTOR_WEIGHTS = {
        "resolution_clarity": 0.25,
        "liquidity": 0.20,
        "time_risk": 0.15,
        "volume_quality": 0.15,
        "spread": 0.15,
        "category_risk": 0.10,
    }

    SUBJECTIVE_KEYWORDS = [
        "effectively",
        "substantially",
        "consensus",
        "arguably",
        "reasonable",
    ]

    HIGH_RISK_CATEGORIES = ["politics", "legal", "regulatory", "geopolitical"]
    LOW_RISK_CATEGORIES = ["sports", "crypto", "weather", "finance", "science"]

    def grade_market(self, market: dict) -> MarketRiskGrade:
        question = market.get("question", "")
        volume = market.get("volume", 0.0)
        liquidity = market.get("liquidity")
        spread = market.get("spread")
        category = market.get("category", "").lower()
        time_to_resolution_hours = market.get("time_to_resolution_hours")
        outcomes_count = market.get("outcomes_count", 2)

        factors: dict[str, float] = {}
        warnings: list[str] = []

        # 1. Resolution clarity
        clarity = 80.0
        found_keywords = [
            kw for kw in self.SUBJECTIVE_KEYWORDS if kw in question.lower()
        ]
        clarity -= len(found_keywords) * 15
        if len(question) > 200:
            clarity -= 10
        if outcomes_count > 5:
            clarity -= 20
        factors["resolution_clarity"] = max(0.0, clarity)
        if found_keywords:
            warnings.append(f"Subjective keywords found: {', '.join(found_keywords)}")

        # 2. Liquidity
        if liquidity is None:
            factors["liquidity"] = 50.0
        elif liquidity > 100_000:
            factors["liquidity"] = 100.0
        elif liquidity > 50_000:
            factors["liquidity"] = 80.0
        elif liquidity > 10_000:
            factors["liquidity"] = 60.0
        elif liquidity > 1_000:
            factors["liquidity"] = 40.0
        elif liquidity > 100:
            factors["liquidity"] = 20.0
        else:
            factors["liquidity"] = 0.0
            warnings.append("Very low liquidity")

        if liquidity is not None and liquidity <= 100:
            if "Very low liquidity" not in warnings:
                warnings.append("Very low liquidity")

        # 3. Time risk
        if time_to_resolution_hours is None:
            factors["time_risk"] = 50.0
        elif time_to_resolution_hours > 168:
            factors["time_risk"] = 100.0
        elif time_to_resolution_hours > 72:
            factors["time_risk"] = 80.0
        elif time_to_resolution_hours > 24:
            factors["time_risk"] = 60.0
        elif time_to_resolution_hours > 6:
            factors["time_risk"] = 40.0
        elif time_to_resolution_hours > 1:
            factors["time_risk"] = 20.0
        else:
            factors["time_risk"] = 10.0

        # 4. Volume quality
        if volume > 1_000_000:
            factors["volume_quality"] = 100.0
        elif volume > 500_000:
            factors["volume_quality"] = 90.0
        elif volume > 100_000:
            factors["volume_quality"] = 70.0
        elif volume > 10_000:
            factors["volume_quality"] = 50.0
        elif volume > 1_000:
            factors["volume_quality"] = 30.0
        else:
            factors["volume_quality"] = 10.0

        # 5. Spread
        if spread is None:
            factors["spread"] = 50.0
        elif spread < 0.01:
            factors["spread"] = 100.0
        elif spread < 0.02:
            factors["spread"] = 80.0
        elif spread < 0.05:
            factors["spread"] = 60.0
        elif spread < 0.10:
            factors["spread"] = 40.0
        elif spread < 0.20:
            factors["spread"] = 20.0
        else:
            factors["spread"] = 0.0
            warnings.append("Very wide spread")

        if spread is not None and spread >= 0.20:
            if "Very wide spread" not in warnings:
                warnings.append("Very wide spread")

        # 6. Category risk
        if category in self.LOW_RISK_CATEGORIES:
            factors["category_risk"] = 90.0
        elif category in self.HIGH_RISK_CATEGORIES:
            factors["category_risk"] = 20.0
            warnings.append(f"High-risk category: {category}")
        else:
            factors["category_risk"] = 50.0

        weighted = sum(factors[f] * w for f, w in self.FACTOR_WEIGHTS.items())
        score = int(round(weighted))

        if score >= 80:
            grade = RiskGrade.A
        elif score >= 60:
            grade = RiskGrade.B
        elif score >= 40:
            grade = RiskGrade.C
        elif score >= 20:
            grade = RiskGrade.D
        else:
            grade = RiskGrade.F

        return MarketRiskGrade(
            grade=grade, score=score, factor_breakdown=factors, warnings=warnings
        )
