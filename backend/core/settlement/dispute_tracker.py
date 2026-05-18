"""
Dispute risk tracker for PolyEdge.

Assesses the likelihood of market resolution disputes based on category,
resolution criteria clarity, volume at stake, and time pressure.
"""
from dataclasses import dataclass
from enum import Enum

# Categories historically associated with higher dispute rates
_HIGH_DISPUTE_CATEGORIES = {"politics", "legal", "regulatory"}

# Keywords that suggest subjective or ambiguous resolution criteria
_SUBJECTIVE_KEYWORDS = {
    "likely",
    "substantially",
    "significant",
    "major",
    "generally",
    "mostly",
    "roughly",
    "approximately",
    "effectively",
    "considered",
    "deemed",
    "arguably",
    "unclear",
    "ambiguous",
    "discretion",
    "judgment",
    "opinion",
}

# Volume threshold above which a market becomes a higher dispute target
_HIGH_VOLUME_USD = 1_000_000.0


class DisputeStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    DISPUTED = "disputed"
    RESOLVED = "resolved"


class ResolutionRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


@dataclass
class DisputeAssessment:
    market_id: str
    status: DisputeStatus
    risk: ResolutionRisk
    risk_score: int  # 0-100
    factors: dict[str, float]
    warnings: list[str]


class DisputeTracker:
    """Assesses market dispute risk from market metadata."""

    def assess_dispute_risk(self, market_data: dict) -> DisputeAssessment:
        """
        Score dispute risk for a single market.

        Factor weights:
          resolution_clarity  40%
          category_risk       30%
          volume_at_stake     15%
          time_pressure       15%
        """
        market_id = str(market_data.get("id") or market_data.get("market_id", "unknown"))
        status = DisputeStatus(market_data.get("status", DisputeStatus.NONE))
        warnings: list[str] = []

        # --- resolution_clarity (0-100, higher = less clear = more risk) ---
        criteria: str = str(market_data.get("resolution_criteria") or market_data.get("question", ""))
        criteria_lower = criteria.lower()
        found_keywords = [kw for kw in _SUBJECTIVE_KEYWORDS if kw in criteria_lower]
        if found_keywords:
            warnings.append(
                f"Subjective resolution keywords detected: {', '.join(found_keywords)}"
            )
        # Each keyword adds 20 points, capped at 100
        clarity_score = min(100.0, len(found_keywords) * 20.0)

        # --- category_risk (0-100) ---
        category: str = str(market_data.get("category", "")).lower()
        if category in _HIGH_DISPUTE_CATEGORIES:
            category_score = 80.0
            warnings.append(f"High-dispute category: {category}")
        else:
            category_score = 20.0

        # --- volume_at_stake (0-100) ---
        volume = float(market_data.get("volume") or market_data.get("volume_usd") or 0.0)
        if volume > _HIGH_VOLUME_USD:
            volume_score = 80.0
            warnings.append(
                f"High volume at stake (${volume:,.0f}) — increased dispute target"
            )
        elif volume > _HIGH_VOLUME_USD * 0.5:
            volume_score = 50.0
        else:
            volume_score = 10.0

        # --- time_pressure (0-100): very short remaining time raises risk ---
        seconds_remaining = float(
            market_data.get("seconds_remaining")
            or market_data.get("time_remaining_seconds")
            or 86400  # default 1 day
        )
        if seconds_remaining < 3600:        # < 1 hour
            time_score = 80.0
            warnings.append("Market closes in < 1 hour — elevated time pressure")
        elif seconds_remaining < 21600:     # < 6 hours
            time_score = 50.0
        else:
            time_score = 10.0

        factors = {
            "resolution_clarity": clarity_score,
            "category_risk": category_score,
            "volume_at_stake": volume_score,
            "time_pressure": time_score,
        }

        # Weighted composite score
        raw = (
            clarity_score * 0.40
            + category_score * 0.30
            + volume_score * 0.15
            + time_score * 0.15
        )
        risk_score = int(max(0, min(100, round(raw))))

        risk = self._score_to_risk(risk_score)

        return DisputeAssessment(
            market_id=market_id,
            status=status,
            risk=risk,
            risk_score=risk_score,
            factors=factors,
            warnings=warnings,
        )

    @staticmethod
    def _score_to_risk(score: int) -> ResolutionRisk:
        if score >= 70:
            return ResolutionRisk.VERY_HIGH
        if score >= 50:
            return ResolutionRisk.HIGH
        if score >= 30:
            return ResolutionRisk.MEDIUM
        return ResolutionRisk.LOW
