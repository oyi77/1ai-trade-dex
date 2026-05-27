"""Arbitrage opportunity scanner across ALL platforms.

Scans ALL prediction market and DEX providers for:
- YES/NO sum arbitrage within each provider
- Complementary/multi-outcome market arbitrage
- Cross-platform price differences between any two providers

Each provider scan has a timeout to prevent hangs.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.strategies.cross_market_arb_enhanced import (
    ArbOpportunityEnhanced,
    CrossMarketArbEnhanced,
    ScanResult,
)

from loguru import logger

# Timeout per provider scan in seconds
_SCAN_TIMEOUT = 30.0

# All prediction-market providers we can scan for arb opportunities.
# Format: (platform_key, scan_method_name)
_PM_PROVIDER_SCANNERS: List[Tuple[str, str]] = [
    ("polymarket", "_scan_polymarket"),
    ("kalshi", "_scan_kalshi"),
    ("sxbet", "_scan_sxbet"),
    ("limitless", "_scan_limitless"),
]


@dataclass
class ArbAlert:
    """An alert for a detected arbitrage opportunity."""

    opportunity: ArbOpportunityEnhanced
    severity: str  # "low" | "medium" | "high"
    message: str
    timestamp: float = field(default_factory=time.time)


class ArbOpportunityScanner:
    """Continuously scans for arbitrage opportunities across ALL platforms."""

    def __init__(
        self,
        min_profit_pct: float = 0.01,
        alert_threshold_pct: float = 0.03,
    ):
        self.detector = CrossMarketArbEnhanced(min_net_profit_pct=min_profit_pct)
        self.alert_threshold = alert_threshold_pct
        self._last_scan: Optional[ScanResult] = None
        self._alerts: List[ArbAlert] = []
        self._max_alerts = 500

    # ── Provider scanners ──────────────────────────────────────────

    async def _scan_polymarket(self) -> List[Dict[str, Any]]:
        """Fetch Polymarket markets via gamma API with pagination."""
        try:
            import httpx
            all_markets = []
            offset = 0
            page_size = 100
            max_pages = 5  # Up to 500 markets
            async with httpx.AsyncClient(timeout=10) as client:
                for _ in range(max_pages):
                    resp = await client.get(
                        "https://gamma-api.polymarket.com/markets",
                        params={"active": "true", "closed": "false", "limit": page_size, "offset": offset},
                    )
                    resp.raise_for_status()
                    page = resp.json()
                    if not page:
                        break
                    all_markets.extend(page)
                    if len(page) < page_size:
                        break
                    offset += page_size
            return _normalize_pm_markets(all_markets, "polymarket", fee_pct=0.02)
        except Exception as e:
            logger.warning(f"arb_scanner: Polymarket fetch failed: {e}")
            return []

    async def _scan_kalshi(self) -> List[Dict[str, Any]]:
        """Fetch Kalshi markets."""
        try:
            from backend.data.kalshi_client import KalshiClient
            client = KalshiClient()
            response = await client.get_markets(params={"limit": 200, "status": "open"})
            raw = response.get("markets", []) if isinstance(response, dict) else []
            return _normalize_kalshi_markets(raw)
        except Exception as e:
            logger.warning(f"arb_scanner: Kalshi fetch failed: {e}")
            return []

    async def _scan_sxbet(self) -> List[Dict[str, Any]]:
        """SXBet: fetch markets + batch orderbook for real prices."""
        try:
            import httpx
            from backend.clients.sxbet_client import SXBetClient

            client = SXBetClient()
            raw = await client.get_markets(limit=100)
            markets = raw.get("data", {}).get("markets", []) if isinstance(raw, dict) else []

            # Batch fetch orders via /orders?marketHashes=X,Y,Z
            import httpx as _httpx
            from collections import defaultdict as _defaultdict

            hashes = [m.get("marketHash", "") for m in markets if m.get("marketHash")]
            all_orders: list = []
            chunk_size = 50
            async with _httpx.AsyncClient(timeout=15.0, follow_redirects=True) as _c:
                for i in range(0, len(hashes), chunk_size):
                    chunk = hashes[i:i + chunk_size]
                    try:
                        _r = await _c.get(
                            f"{client._base_url}/orders",
                            params={"marketHashes": ",".join(chunk)},
                        )
                        _data = _r.json() if _r.status_code == 200 else {}
                        _orders = _data.get("data", [])
                        if isinstance(_orders, list):
                            all_orders.extend(_orders)
                    except Exception:
                        continue

            # Group best prices per outcome
            by_market: dict = _defaultdict(lambda: {"yes_orders": [], "no_orders": []})
            for o in all_orders:
                mh = o.get("marketHash", "")
                odds_pct = float(o.get("percentageOdds", 0)) / 1e18
                price = odds_pct / 100.0
                if not (0 < price < 1):
                    continue
                is_yes = o.get("isMakerBettingOutcomeOne", True)
                if is_yes:
                    by_market[mh]["yes_orders"].append(price)
                else:
                    by_market[mh]["no_orders"].append(price)

            normalized = []
            for m in markets:
                mh = m.get("marketHash", "")
                prices = by_market.get(mh, {})
                yes_prices = sorted(prices.get("yes_orders", []), reverse=True)
                no_prices = sorted(prices.get("no_orders", []), reverse=True)
                yes_price = yes_prices[0] if yes_prices else None
                no_price = no_prices[0] if no_prices else (1.0 - yes_price if yes_price else 0.5)

                if yes_price is None or not (0 < yes_price < 1):
                    continue

                normalized.append({
                    "question": _sxbet_question(m),
                    "event_id": mh,
                    "yes_price": yes_price,
                    "no_price": no_price if 0 < no_price < 1 else round(1.0 - yes_price, 4),
                    "platform": "sxbet",
                    "fee_pct": 0.02,
                    "liquidity": float(m.get("liquidity", 0) or 0),
                    "volume": float(m.get("volume", 0) or 0),
                    "_raw": m,
                })
            return normalized
        except Exception as e:
            logger.warning(f"arb_scanner: SXBet fetch failed: {e}")
            return []

    async def _scan_myriad(self) -> List[Dict[str, Any]]:
        """Myriad: API 404s, skip for now."""
        return []

    async def _scan_predictfun(self) -> List[Dict[str, Any]]:
        """predict.fun: hardcodes yes_price=0.5, not arb-usable yet."""
        return []

    async def _scan_bookmaker(self) -> List[Dict[str, Any]]:
        """Fetch Bookmaker.xyz markets."""
        try:
            from backend.markets.providers.bookmaker_xyz_provider import BookmakerXYZProvider
            provider = BookmakerXYZProvider()
            markets = await provider.get_markets(limit=100)
            return _normalize_provider_markets(markets, "bookmaker_xyz", fee_pct=0.02)
        except Exception as e:
            logger.warning(f"arb_scanner: Bookmaker.xyz fetch failed: {e}")
            return []

    async def _scan_limitless(self) -> List[Dict[str, Any]]:
        """Fetch Limitless Exchange active markets with real prices."""
        try:
            from backend.clients.limitless_client import LimitlessClient
            client = LimitlessClient()
            markets = await client.get_markets(limit=100)
            normalized = []
            for m in markets:
                if not isinstance(m, dict):
                    continue
                prices = m.get("prices", [])
                if not isinstance(prices, list) or len(prices) < 2:
                    continue
                yes_price = float(prices[0]) if prices[0] else None
                no_price = float(prices[1]) if prices[1] else None
                if yes_price is None or not (0 < yes_price < 1):
                    continue
                title = m.get("title", "") or m.get("proxyTitle", "")
                normalized.append({
                    "question": title,
                    "event_id": str(m.get("conditionId", m.get("id", ""))),
                    "yes_price": yes_price,
                    "no_price": no_price if no_price else round(1.0 - yes_price, 4),
                    "platform": "limitless",
                    "fee_pct": 0.02,
                    "liquidity": float(m.get("volume", 0) or 0),
                    "volume": float(m.get("volume", 0) or 0),
                    "_raw": m,
                })
            return normalized
        except Exception as e:
            logger.warning(f"arb_scanner: Limitless fetch failed: {e}")
            return []

    # ── Main scan loop ─────────────────────────────────────────────

    async def run_scan(self) -> ScanResult:
        """Run a full arbitrage scan across ALL providers in parallel."""
        all_provider_markets: Dict[str, List[Dict[str, Any]]] = {}

        # Fetch from all providers in parallel
        scan_methods = {
            name: getattr(self, method_name)
            for name, method_name in _PM_PROVIDER_SCANNERS
        }

        async def _scan_with_timeout(method):
            try:
                return await asyncio.wait_for(method(), timeout=_SCAN_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(f"arb_scanner: {method.__self__.__class__.__name__} timed out after {_SCAN_TIMEOUT}s")
                return []
            except Exception as e:
                logger.warning(f"arb_scanner: scan failed: {e}")
                return []

        results = await asyncio.gather(
            *[_scan_with_timeout(m) for m in scan_methods.values()],
            return_exceptions=True,
        )

        for (name, _), result in zip(_PM_PROVIDER_SCANNERS, results):
            if isinstance(result, Exception):
                logger.warning(f"arb_scanner: {name} scan exception: {result}")
                all_provider_markets[name] = []
            else:
                all_provider_markets[name] = result or []

        # Run detector across ALL providers
        result = self.detector.scan_all_providers(all_provider_markets)
        self._last_scan = result
        self._generate_alerts(result)

        logger.info(
            f"arb_scanner: scanned {result.markets_scanned} markets across "
            f"{len(all_provider_markets)} providers, "
            f"found {len(result.opportunities)} opportunities in {result.scan_duration_ms:.1f}ms"
        )
        return result

    def _generate_alerts(self, result: ScanResult) -> None:
        """Generate alerts for high-profit opportunities."""
        for opp in result.opportunities:
            if opp.net_profit_pct >= self.alert_threshold:
                severity = "high" if opp.net_profit_pct >= 0.05 else "medium"
                self._alerts.append(
                    ArbAlert(
                        opportunity=opp,
                        severity=severity,
                        message=(
                            f"Arb opportunity: {opp.kind} on {opp.platform_a}/{opp.platform_b} "
                            f"net={opp.net_profit:.4f} ({opp.net_profit_pct:.1%})"
                        ),
                    )
                )
                if len(self._alerts) > self._max_alerts:
                    self._alerts = self._alerts[-self._max_alerts :]

    @property
    def last_scan(self) -> Optional[ScanResult]:
        return self._last_scan

    @property
    def recent_alerts(self) -> List[ArbAlert]:
        return self._alerts[-50:]

    def get_stats(self) -> Dict[str, Any]:
        """Return scanner statistics."""
        return {
            "last_scan_opportunities": (
                len(self._last_scan.opportunities) if self._last_scan else 0
            ),
            "last_scan_duration_ms": (
                self._last_scan.scan_duration_ms if self._last_scan else 0
            ),
            "total_alerts": len(self._alerts),
            "high_severity_alerts": sum(
                1 for a in self._alerts if a.severity == "high"
            ),
        }


# ── Market normalization helpers ────────────────────────────────────

def _normalize_pm_markets(
    raw: List[Dict[str, Any]], platform: str, fee_pct: float = 0.02
) -> List[Dict[str, Any]]:
    """Normalize Polymarket/Gamma markets."""
    normalized = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        yes_price, no_price = _extract_yes_no_from_outcome_prices(m)
        if yes_price is None:
            continue
        # Extract clobTokenIds for live CLOB execution
        clob_token_ids = m.get("clobTokenIds") or []
        if isinstance(clob_token_ids, str):
            import json as _json
            try:
                clob_token_ids = _json.loads(clob_token_ids)
            except Exception:
                clob_token_ids = []

        normalized.append({
            "question": m.get("question", ""),
            "event_id": str(m.get("conditionId", m.get("id", ""))),
            "yes_price": yes_price,
            "no_price": no_price,
            "platform": platform,
            "fee_pct": fee_pct,
            "liquidity": float(m.get("liquidity", 0) or 0),
            "volume": float(m.get("volume", 0) or 0),
            "clobTokenIds": clob_token_ids,
            "_raw": m,
        })
    return normalized


def _normalize_kalshi_markets(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize Kalshi markets. Kalshi uses 'title' not 'question'."""
    normalized = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        title = m.get("title", "")
        if not title:
            continue
        # Kalshi: yes_ask_dollars = price to buy YES, yes_bid_dollars = price to sell YES
        ask = float(m.get("yes_ask_dollars", 0) or 0)
        bid = float(m.get("yes_bid_dollars", 0) or 0)
        last = float(m.get("last_price_dollars", 0) or 0)
        # Use mid or last as YES price, (1 - yes) as NO price
        yes_price = last if 0 < last < 1 else (ask if 0 < ask < 1 else (bid if 0 < bid < 1 else None))
        if yes_price is None:
            continue
        normalized.append({
            "question": title,  # Kalshi uses 'title' as question text
            "event_id": str(m.get("ticker", m.get("event_ticker", ""))),
            "yes_price": yes_price,
            "no_price": round(1.0 - yes_price, 4),
            "platform": "kalshi",
            "fee_pct": 0.07,
            "liquidity": float(m.get("liquidity_dollars", 0) or 0),
            "volume": float(m.get("volume_24h_fp", 0) or 0),
            "_raw": m,
        })
    return normalized


def _sxbet_question(m: dict) -> str:
    """Extract readable question from SXBet market data."""
    t1 = m.get("teamOneName", "") or m.get("outcomeOneName", "")
    t2 = m.get("teamTwoName", "") or m.get("outcomeTwoName", "")
    if t1 and t2:
        return f"{t1} vs {t2}"
    return m.get("title", m.get("question", str(m.get("marketHash", ""))))


def _normalize_provider_markets(
    raw: List, platform: str, fee_pct: float = 0.02
) -> List[Dict[str, Any]]:
    """Normalize markets from provider MarketInfo objects or raw dicts."""
    normalized = []
    for m in raw:
        if hasattr(m, '__dict__'):
            # MarketInfo / dataclass
            d = m.__dict__ if hasattr(m, '__dict__') else {}
            question = d.get("question", "") or d.get("title", "") or d.get("description", "")
            yes_price = float(d.get("yes_price", 0) or 0)
            no_price = float(d.get("no_price", 0) or 0)
            event_id = str(d.get("market_id", d.get("id", d.get("conditionId", ""))))
        elif isinstance(m, dict):
            question = m.get("question", "") or m.get("title", "") or m.get("description", "")
            yes_price = _extract_yes_price_from_dict(m)
            no_price = 1.0 - yes_price if yes_price else 0.5
            event_id = str(m.get("market_id") or m.get("id") or m.get("conditionId") or m.get("marketHash") or "")
        else:
            continue

        if not question or yes_price is None or not (0 < yes_price < 1):
            continue

        normalized.append({
            "question": question,
            "event_id": event_id,
            "yes_price": yes_price,
            "no_price": no_price,
            "platform": platform,
            "fee_pct": fee_pct,
            "liquidity": 0.0,
            "volume": 0.0,
            "_raw": m,
        })
    return normalized


def _extract_yes_price_from_dict(m: Dict[str, Any]) -> Optional[float]:
    """Extract YES price from various market dict formats."""
    for key in ("yes_price", "yesPrice", "price", "last_price_dollars", "yes_ask_dollars"):
        val = m.get(key)
        if val is not None:
            try:
                p = float(val)
                if 0 < p < 1:
                    return p
            except (ValueError, TypeError):
                pass

    op = m.get("outcomePrices")
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
            logger.warning("arb_opp_scanner: failed to extract price from outcomePrices")

    # Check for yes_sub_title / no_sub_title (Kalshi multi-outcome)
    outcomes = m.get("outcomes")
    if isinstance(outcomes, list):
        for o in outcomes:
            if isinstance(o, dict) and o.get("name", "").lower() == "yes":
                p = o.get("price")
                if p is not None:
                    try:
                        pp = float(p)
                        if 0 < pp < 1:
                            return pp
                    except (ValueError, TypeError):
                        pass
    return None


def _extract_yes_no_from_outcome_prices(m: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Extract YES and NO prices from outcomePrices array."""
    op = m.get("outcomePrices")
    if not op:
        return (None, None)
    try:
        import json as _json
        if isinstance(op, str):
            op = _json.loads(op)
        if isinstance(op, list) and len(op) >= 2:
            yes = float(op[0])
            no = float(op[1])
            if 0 < yes < 1 and 0 < no < 1:
                return (yes, no)
        if isinstance(op, list) and len(op) == 1:
            yes = float(op[0])
            if 0 < yes < 1:
                return (yes, 1.0 - yes)
    except Exception:
        logger.warning("arb_opp_scanner: failed to extract yes/no from outcomePrices")
    return (None, None)
