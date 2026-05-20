"""Arbitrage opportunity scanner across platforms.

Scans Polymarket and Kalshi for cross-platform arbitrage,
complementary market arbitrage, and yes/no sum arbitrage.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.strategies.cross_market_arb_enhanced import (
    ArbOpportunityEnhanced,
    CrossMarketArbEnhanced,
    ScanResult,
)

from loguru import logger


@dataclass
class ArbAlert:
    """An alert for a detected arbitrage opportunity."""

    opportunity: ArbOpportunityEnhanced
    severity: str  # "low" | "medium" | "high"
    message: str
    timestamp: float = field(default_factory=time.time)


class ArbOpportunityScanner:
    """Continuously scans for arbitrage opportunities across platforms."""

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

    async def scan_polymarket_markets(self) -> List[Dict[str, Any]]:
        """Fetch Polymarket markets for scanning."""
        try:
            from backend.data.gamma import fetch_markets

            return await fetch_markets(limit=200)
        except Exception as e:
            logger.warning(f"arb_scanner: Polymarket fetch failed: {e}")
            return []

    async def scan_kalshi_markets(self) -> List[Dict[str, Any]]:
        """Fetch Kalshi markets for scanning."""
        try:
            from backend.data.kalshi_client import KalshiClient

            client = KalshiClient()
            return await client.get_markets(params={"limit": 200})
        except Exception as e:
            logger.warning(f"arb_scanner: Kalshi fetch failed: {e}")
            return []

    async def run_scan(self) -> ScanResult:
        """Run a full arbitrage scan across all platforms."""
        poly_markets, kalshi_markets = await asyncio.gather(
            self.scan_polymarket_markets(),
            self.scan_kalshi_markets(),
        )

        result = self.detector.scan_all(poly_markets, kalshi_markets)
        self._last_scan = result
        self._generate_alerts(result)

        logger.info(
            f"arb_scanner: scanned {result.markets_scanned} markets, "
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
