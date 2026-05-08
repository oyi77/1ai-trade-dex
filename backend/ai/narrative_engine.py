"""Narrative market classifier — penalizes hype/narrative markets where base rate for 'Yes' is extremely low."""
import logging

from backend.ai.probability_utils import clamp_probability

logger = logging.getLogger("trading_bot.narrative")

NARRATIVE_KEYWORDS = [
    "will", "could", "might", "should", "trump", "elon", "musk", "celebrity",
    "tweet", "announce", "reveal", "confirm", "deny", "allegation", "lawsuit",
    "verdict", "trial", "plead", "guilty", "innocent", "scandal", "resign",
    "fired", "hired", "appoint", "nominate", "run for", "elected", "vote",
    "poll", "survey", "approval", "rating", "popular", "viral", "trending",
]


def classify_market_type(market_title: str, description: str = "") -> str:
    """Classify if market is narrative/hype vs data-driven."""
    text = f"{market_title} {description}".lower()
    keyword_hits = sum(1 for kw in NARRATIVE_KEYWORDS if kw in text)
    if keyword_hits >= 3:
        return "narrative"
    if keyword_hits >= 1 and any(w in text for w in ["trump", "elon", "musk", "celebrity", "tweet", "viral"]):
        return "narrative"
    return "data_driven"


def apply_narrative_penalty(raw_probability: float, market_type: str) -> float:
    """Apply mathematical penalty for narrative markets."""
    if market_type != "narrative":
        return raw_probability
    penalty = 0.40
    adjusted = raw_probability - penalty
    return clamp_probability(adjusted)
