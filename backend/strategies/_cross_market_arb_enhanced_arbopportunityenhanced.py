"""Carved verbatim out of ``backend/strategies/cross_market_arb_enhanced.py`` — statements moved, no logic changed."""

from __future__ import annotations

from .cross_market_arb_enhanced import (
    Any,
    Dict,
    Optional,
    dataclass,
)

from . import cross_market_arb_enhanced as _facade

@dataclass
class ArbOpportunityEnhanced:
    """An enhanced arbitrage opportunity with full cost modeling."""

    event_id: str
    kind: str  # "cross_platform" | "complementary" | "yes_no_sum"
    platform_a: str
    platform_b: str
    market_a_id: str
    market_b_id: str
    price_a: float
    price_b: float
    raw_spread: float
    fees: float
    slippage_cost: float
    execution_risk: float
    net_profit: float
    net_profit_pct: float
    confidence: float
    token_id: _facade.Optional[str] = None
    platform: str = ""
    details: _facade.Dict[str, _facade.Any] = _facade.field(default_factory=dict)
@dataclass
class ScanResult:
    """Result of an arbitrage scan."""

    opportunities: _facade.List[ArbOpportunityEnhanced]
    markets_scanned: int
    scan_duration_ms: float
    platform: str = "multi"
def _extract_yes_price(market: Dict[str, Any]) -> Optional[float]:
    """Extract YES price from a market dict (legacy, use market['yes_price'] directly)."""
    # First check normalized fields
    yp = market.get("yes_price")
    if yp is not None:
        try:
            p = float(yp)
            if 0 < p < 1:
                return p
        except (ValueError, TypeError):
            _facade.logger.debug("cross_market_arb: failed to parse yes_price from market")

    for key in ("yesPrice", "price"):
        val = market.get(key)
        if val is not None:
            try:
                p = float(val)
                if 0 < p < 1:
                    return p
            except (ValueError, TypeError):
                _facade.logger.debug("cross_market_arb: failed to parse price from market key")

    op = market.get("outcomePrices")
    if op:
        try:
            import json as _json

            if isinstance(op, str):
                op = _json.loads(op)
            if isinstance(op, list) and len(op) >= 1:
                p = float(op[0])
                if 0 < p < 1:
                    return p
        except Exception:
            _facade.logger.warning(
                "cross_market_arb_enhanced: failed to parse Kalshi orderbook price"
            )

    kalshi_ask = market.get("yes_ask_dollars")
    if kalshi_ask is not None:
        try:
            p = float(kalshi_ask)
            if 0 < p < 1:
                return p
        except (ValueError, TypeError):
            _facade.logger.debug("cross_market_arb: failed to parse kalshi yes_ask_dollars")
    return None
def _normalize_number(text: str) -> str:
    """Normalize numbers in text: 100k -> 100000, $100,000 -> 100000."""
    import re

    def _replace(match):
        s = match.group(0).lower().replace(",", "").replace("$", "").strip()
        multiplier = 1
        if s.endswith("k"):
            s = s[:-1]
            multiplier = 1_000
        elif s.endswith("m"):
            s = s[:-1]
            multiplier = 1_000_000
        elif s.endswith("b"):
            s = s[:-1]
            multiplier = 1_000_000_000
        try:
            return str(int(float(s) * multiplier))
        except (ValueError, TypeError):
            return match.group(0)

    return re.sub(r"[\$]?[\d,]+\.?\d*[kKmMbB]?", _replace, text)
def _normalize_crypto_tokens(text: str) -> str:
    """Replace crypto synonyms with canonical tokens."""
    words = text.lower().split()
    normalized = [_facade._CRYPTO_SYNONYMS.get(w, w) for w in words]
    return " ".join(normalized)
def _questions_match(q1: str, q2: str) -> bool:
    """Check if two questions refer to the same event.

    Uses Jaccard similarity on meaningful words + entity matching.
    Requires >= 60% overlap on the SMALLER set AND at least 3 matching words.
    Both questions must have >= 3 meaningful words to prevent short-question noise.

    Enhanced with number normalization (100k = $100,000 = 100000)
    and crypto synonym normalization (Bitcoin = BTC, Ethereum = ETH).
    """
    import re

    # Normalize: numbers, crypto synonyms, strip punctuation, then tokenize
    n1 = _normalize_crypto_tokens(_normalize_number(q1.lower()))
    n2 = _normalize_crypto_tokens(_normalize_number(q2.lower()))

    # Strip punctuation from tokens
    def _clean(s: str) -> set[str]:
        import re as re2

        return {re2.sub(r"[^a-z0-9]", "", w) for w in s.split()} - {""}

    words1 = _clean(n1) - _facade._STOP_WORDS
    words2 = _clean(n2) - _facade._STOP_WORDS
    if not words1 or not words2:
        return False

    # Both questions need enough substance for reliable matching
    if len(words1) < 2 or len(words2) < 2:
        return False

    overlap = words1 & words2
    smaller = min(len(words1), len(words2))
    if smaller == 0 or len(overlap) == 0:
        return False

    # Need at least 50% overlap on smaller set AND at least 2 matching words
    if len(overlap) < 2:
        return False
    if len(overlap) / smaller < 0.5:
        return False

    # Entity check: numbers and proper nouns must overlap
    def _entities(text: str) -> set[str]:
        tokens = set()
        for tok in re.findall(r"[A-Za-z0-9]+", text):
            if tok[0].isdigit() or (
                len(tok) > 1 and tok[0].isupper() and tok.lower() not in _facade._STOP_WORDS
            ):
                tokens.add(tok.lower())
        return tokens

    ent1 = _entities(n1)
    ent2 = _entities(n2)
    if ent1 and ent2:
        if not (ent1 & ent2):
            return False

    return True
