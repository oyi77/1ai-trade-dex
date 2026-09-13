"""Enhanced cross-market arbitrage detection for ALL prediction-market providers.

Supports:
- YES/NO sum arbitrage within each provider
- Complementary/multi-outcome market detection
- Cross-platform price difference scanning between ALL providers
- Generic 2-provider spread computation with platform-specific fees
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from backend.core.strategy_gate import StrategyGate

_DEFAULT_FEES = {
    "polymarket": 0.02,
    "kalshi": 0.07,
    "sxbet": 0.02,
    "myriad": 0.02,
    "predict_fun": 0.02,
    "bookmaker_xyz": 0.02,
    "limitless": 0.02,
}
_STOP_WORDS = frozenset(
    {
        "will",
        "the",
        "be",
        "in",
        "a",
        "an",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "is",
        "it",
        "by",
        "as",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "was",
        "were",
        "are",
        "this",
        "that",
        "with",
        "from",
        "but",
        "not",
        "no",
        "if",
        "so",
        "than",
        # Short-duration market noise
        "up",
        "down",
        "min",
        "hourly",
        "daily",
        "weekly",
        "monthly",
        "et",
        "am",
        "pm",
        "yes",
        "before",
        "after",
        "between",
        "above",
        "below",
        "over",
        "under",
    }
)
_CRYPTO_SYNONYMS = {
    "bitcoin": "btc",
    "btc": "btc",
    "ethereum": "eth",
    "eth": "eth",
    "solana": "sol",
    "sol": "sol",
    "xrp": "xrp",
    "ripple": "xrp",
    "dogecoin": "doge",
    "doge": "doge",
    "cardano": "ada",
    "ada": "ada",
    "bnb": "bnb",
    "binance": "bnb",
    "polkadot": "dot",
    "dot": "dot",
    "avax": "avax",
    "avalanche": "avax",
    "matic": "matic",
    "polygon": "matic",
    "link": "link",
    "chainlink": "link",
}

from ._cross_market_arb_enhanced_arbopportunityenhanced import (  # noqa: E402  (must follow the names it imports back)
    ArbOpportunityEnhanced,
    ScanResult,
    _extract_yes_price,
    _normalize_crypto_tokens,
    _normalize_number,
    _questions_match,
)

from ._cross_market_arb_enhanced_crossmarketarbenhanced import (  # noqa: E402  (must follow the names it imports back)
    CrossMarketArbEnhanced,
)


__all__ = [
    "Any",
    "ArbOpportunityEnhanced",
    "CrossMarketArbEnhanced",
    "Dict",
    "List",
    "Optional",
    "ScanResult",
    "StrategyGate",
    "Tuple",
    "_CRYPTO_SYNONYMS",
    "_DEFAULT_FEES",
    "_STOP_WORDS",
    "_extract_yes_price",
    "_normalize_crypto_tokens",
    "_normalize_number",
    "_questions_match",
    "dataclass",
    "field",
    "logger",
    "time",
]
