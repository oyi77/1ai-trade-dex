"""APEX market scanner — discovers structural edges across Polymarket.

Reuses MarketUniverseScanner for market discovery, adds edge detection
on top: stale odds, resolution timing, liquidity gaps, orderbook imbalance,
and time-decay opportunities.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from backend.core.edge.edge_types import (
    EdgeSignal,
    EdgeType,
    MarketSnapshot,
    StructuralInefficiency,
    clamp,
)

logger = logging.getLogger(__name__)


class APEXMarketScanner:
    """Scans Polymarket markets for structural edge opportunities.

    Uses Gamma API + CLOB data to detect mispriced markets, stale odds,
    resolution timing edges, and liquidity gaps.
    """

    def __init__(self, settings_obj: Any = None):
        from backend.config import settings as _settings

        self.settings = settings_obj or _settings
        self._cache: dict[str, MarketSnapshot] = {}
        self._cache_ttl = 120.0  # seconds
        self._last_scan: datetime | None = None

    async def scan(self, markets: list[dict[str, Any]] | None = None) -> list[EdgeSignal]:
        """Full scan cycle: fetch markets, classify, detect edges.

        Args:
            markets: Pre-fetched market dicts from Gamma API. If None,
                      will fetch internally.

        Returns:
            List of EdgeSignal opportunities sorted by expected value.
        """
        if markets is None:
            markets = await self._fetch_markets()

        snapshots = await self._build_snapshots(markets)
        edges: list[EdgeSignal] = []

        for snap in snapshots:
            edges.extend(self._check_stale_odds(snap))
            edges.extend(self._check_resolution_timing(snap))
            edges.extend(self._check_liquidity_gap(snap))
            edges.extend(self._check_time_decay(snap))

        # Sort by expected value (edge * confidence)
        edges.sort(key=lambda s: s.expected_value, reverse=True)

        self._last_scan = datetime.now(timezone.utc)
        logger.info(f"APEX scan: {len(snapshots)} markets, {len(edges)} edges detected")
        return edges

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        """Fetch active markets from Gamma API."""
        try:
            from backend.data.gamma import GammaClient

            gamma = GammaClient(self.settings)
            markets = await gamma.fetch_markets(limit=500, active=True, order="volume")
            return markets or []
        except Exception as e:
            logger.warning(f"APEX: Failed to fetch markets from Gamma: {e}")
            return []

    async def _build_snapshots(
        self, markets: list[dict[str, Any]]
    ) -> list[MarketSnapshot]:
        """Convert raw market dicts to MarketSnapshot objects."""
        snapshots = []

        for m in markets:
            try:
                # Extract prices from CLOB token data or outcome prices
                yes_price = 0.5
                no_price = 0.5
                if isinstance(m.get("outcomePrices"), str):
                    prices = m["outcomePrices"].strip("[]").split(",")
                    if len(prices) >= 2:
                        yes_price = float(prices[0].strip().strip('"'))
                        no_price = float(prices[1].strip().strip('"'))
                elif isinstance(m.get("outcomePrices"), list):
                    prices = m["outcomePrices"]
                    if len(prices) >= 2:
                        yes_price = float(prices[0])
                        no_price = float(prices[1])

                # Parse end date
                end_date = None
                end_date_str = m.get("endDate") or m.get("end_date_iso")
                if end_date_str:
                    try:
                        end_date = datetime.fromisoformat(
                            end_date_str.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        pass

                # Parse volume
                volume = float(m.get("volume", 0) or 0)
                liquidity = float(m.get("liquidity", 0) or m.get("liquidityNum", 0) or 0)

                # Parse token ID
                token_id = ""
                tokens = m.get("tokens") or m.get("clobTokenIds")
                if isinstance(tokens, list) and len(tokens) > 0:
                    if isinstance(tokens[0], dict):
                        token_id = tokens[0].get("token_id", "")
                    else:
                        token_id = str(tokens[0])

                # Market metadata
                ticker = m.get("conditionId", m.get("question", ""))[:64]
                category = m.get("category", "unknown")
                question = m.get("question", "")

                # Compute spread from prices
                spread = abs(yes_price - (1 - no_price)) if yes_price and no_price else 0.0

                # Parse last price change timestamp
                last_price_change_at = None
                change_ts = m.get("lastPriceChangeAt") or m.get("last_price_change_at")
                if change_ts:
                    try:
                        last_price_change_at = datetime.fromisoformat(
                            change_ts.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        pass

                snap = MarketSnapshot(
                    ticker=ticker,
                    token_id=token_id,
                    yes_price=yes_price,
                    no_price=no_price,
                    volume=volume,
                    liquidity=liquidity,
                    spread=spread,
                    bid_depth=liquidity * 0.5,  # estimate
                    ask_depth=liquidity * 0.5,  # estimate
                    last_price_change_at=last_price_change_at,
                    end_date=end_date,
                    category=category,
                    question=question,
                    metadata=m,
                )
                snapshots.append(snap)
            except Exception as e:
                logger.debug(f"APEX: Skipping market due to parse error: {e}")
                continue

        return snapshots

    def _check_stale_odds(self, snap: MarketSnapshot) -> list[EdgeSignal]:
        """Detect markets where odds haven't moved recently.

        Stale odds suggest information hasn't been priced in yet.
        """
        signals = []
        threshold_minutes = getattr(self.settings, "APEX_STALE_ODDS_THRESHOLD_MINUTES", 30)

        if snap.last_price_change_at is None:
            return signals

        now = datetime.now(timezone.utc)
        staleness_minutes = (now - snap.last_price_change_at).total_seconds() / 60

        if staleness_minutes > threshold_minutes and snap.volume > 1000:
            # Stale odds: if price is extreme, the market may have mispriced
            if snap.yes_price > 0.85 or snap.yes_price < 0.15:
                direction = "YES" if snap.yes_price > 0.85 else "NO"
                edge_pp = min(staleness_minutes / 60, 10.0) * (0.5 if direction == "NO" else 0.5)
                confidence = clamp(0.3 + 0.1 * min(staleness_minutes / threshold_minutes, 3), 0.1, 0.7)

                signals.append(
                    EdgeSignal(
                        market_ticker=snap.ticker,
                        token_id=snap.token_id,
                        edge_type=EdgeType.STALE_ODDS,
                        direction=direction,
                        model_probability=snap.yes_price if direction == "YES" else 1 - snap.yes_price,
                        market_price=snap.yes_price,
                        edge_pp=edge_pp,
                        confidence=confidence,
                        time_to_resolution_hours=snap.time_to_resolution_hours or 999,
                        metadata={"staleness_minutes": staleness_minutes},
                        expires_at=now + timedelta(minutes=threshold_minutes),
                    )
                )

        return signals

    def _check_resolution_timing(self, snap: MarketSnapshot) -> list[EdgeSignal]:
        """Detect near-resolution markets with high certainty.

        Markets approaching resolution with extreme prices have
        predictable outcomes — theta works in our favor.
        """
        signals = []
        min_price = getattr(self.settings, "APEX_NEAR_RESOLUTION_MIN_PRICE", 0.85)
        max_hours = getattr(self.settings, "APEX_NEAR_RESOLUTION_MAX_HOURS", 72)
        min_hours = getattr(self.settings, "APEX_NEAR_RESOLUTION_MIN_HOURS", 1)

        hours_left = snap.time_to_resolution_hours
        if hours_left is None:
            return signals

        if not (min_hours <= hours_left <= max_hours):
            return signals

        # High-certainty YES or NO near resolution
        if snap.yes_price > min_price:
            prob = snap.yes_price + (1 - snap.yes_price) * 0.1
            edge_pp = (prob - snap.yes_price) * 100
            confidence = clamp(0.7 + 0.3 * (1 - hours_left / max_hours), 0.4, 0.95)
            direction = "YES"
        elif snap.yes_price < (1 - min_price):
            prob = 1 - (1 - snap.yes_price + snap.yes_price * 0.1)
            edge_pp = ((1 - snap.yes_price) - (1 - snap.yes_price) * 0.9) * 100
            confidence = clamp(0.7 + 0.3 * (1 - hours_left / max_hours), 0.4, 0.95)
            direction = "NO"
        else:
            return signals

        if edge_pp < getattr(self.settings, "APEX_MIN_EDGE_PP", 2.0):
            return signals

        signals.append(
            EdgeSignal(
                market_ticker=snap.ticker,
                token_id=snap.token_id,
                edge_type=EdgeType.RESOLUTION_TIMING,
                direction=direction,
                model_probability=clamp(prob if direction == "YES" else 1 - prob, 0.01, 0.99),
                market_price=snap.yes_price,
                edge_pp=edge_pp,
                confidence=confidence,
                time_to_resolution_hours=hours_left,
                metadata={"hours_to_resolution": hours_left},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=min(hours_left * 0.5, 12)),
            )
        )
        return signals

    def _check_liquidity_gap(self, snap: MarketSnapshot) -> list[EdgeSignal]:
        """Detect markets with wide spreads that present opportunities.

        Wide spreads on high-volume markets suggest market makers are
        uncertain or demand premium — potential for limit order edge.
        """
        signals = []
        min_spread = getattr(self.settings, "APEX_LIQUIDITY_GAP_MIN_SPREAD", 0.03)
        min_volume = getattr(self.settings, "APEX_LIQUIDITY_GAP_MIN_VOLUME", 5000)

        if snap.spread < min_spread or snap.volume < min_volume:
            return signals

        # Wide spread = we can place limit orders inside the spread
        # Edge is approximately half the spread
        edge_pp = snap.spread * 50  # convert spread to pp
        confidence = clamp(0.3 + 0.2 * min(snap.volume / 50000, 1.0), 0.2, 0.6)

        # Direction depends on where the true price likely sits
        mid = snap.mid_price
        direction = "YES" if mid > 0.5 else "NO"

        signals.append(
            EdgeSignal(
                market_ticker=snap.ticker,
                token_id=snap.token_id,
                edge_type=EdgeType.LIQUIDITY_GAP,
                direction=direction,
                model_probability=mid,
                market_price=snap.yes_price,
                edge_pp=edge_pp,
                confidence=confidence,
                time_to_resolution_hours=snap.time_to_resolution_hours or 999,
                metadata={"spread": snap.spread, "volume": snap.volume},
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        return signals

    def _check_time_decay(self, snap: MarketSnapshot) -> list[EdgeSignal]:
        """Detect theta-decay edges on binary options.

        Binary options with extreme probabilities decay toward 1.0 or 0.0
        as resolution approaches. If the market hasn't fully priced this
        decay, there's an edge in holding to resolution.
        """
        signals = []
        hours_left = snap.time_to_resolution_hours
        if hours_left is None or hours_left > 168:  # > 7 days: decay too small
            return signals

        # Time decay is most valuable for moderate-to-high certainty markets
        # with short time to resolution
        if snap.yes_price < 0.70 and snap.yes_price > 0.30:
            return signals  # Not enough certainty for theta edge

        # Estimate theta: how much probability should move per hour
        # For a binary near resolution: theta ≈ (1 - price) / hours_left for YES
        if snap.yes_price > 0.70:
            # YES side theta: probability should drift toward 1.0
            theta_per_hour = (1.0 - snap.yes_price) / max(hours_left, 1)
            edge_pp = theta_per_hour * 100 * 0.5  # conservative: half of theoretical theta
            direction = "YES"
            model_prob = snap.yes_price + theta_per_hour * hours_left * 0.5
        else:
            # NO side theta
            theta_per_hour = snap.yes_price / max(hours_left, 1)
            edge_pp = theta_per_hour * 100 * 0.5
            direction = "NO"
            model_prob = snap.yes_price - theta_per_hour * hours_left * 0.5

        if edge_pp < getattr(self.settings, "APEX_MIN_EDGE_PP", 2.0):
            return signals

        confidence = clamp(0.4 + 0.3 * (1 - hours_left / 168), 0.2, 0.8)

        signals.append(
            EdgeSignal(
                market_ticker=snap.ticker,
                token_id=snap.token_id,
                edge_type=EdgeType.TIME_DECAY,
                direction=direction,
                model_probability=clamp(model_prob, 0.01, 0.99),
                market_price=snap.yes_price,
                edge_pp=edge_pp,
                confidence=confidence,
                time_to_resolution_hours=hours_left,
                metadata={"theta_per_hour": theta_per_hour, "hours_left": hours_left},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=min(hours_left * 0.5, 24)),
            )
        )
        return signals

    def detect_inefficiencies(self, snap: MarketSnapshot) -> list[StructuralInefficiency]:
        """Detect structural inefficiencies (informational, not necessarily tradeable)."""
        inefficiencies: list[StructuralInefficiency] = []
        now = datetime.now(timezone.utc)

        # Stale odds without enough volume for trading
        if snap.last_price_change_at:
            staleness = (now - snap.last_price_change_at).total_seconds() / 60
            if staleness > 60 and snap.volume < 1000:
                inefficiencies.append(
                    StructuralInefficiency(
                        market_ticker=snap.ticker,
                        inefficiency_type="stale_low_volume",
                        severity=clamp(staleness / 120, 0, 1),
                        description=f"No price change in {staleness:.0f} min, volume ${snap.volume:.0f}",
                        detected_at=now,
                    )
                )

        # Wide spread on low-liquidity market
        if snap.spread > 0.10 and snap.liquidity < 500:
            inefficiencies.append(
                StructuralInefficiency(
                    market_ticker=snap.ticker,
                    inefficiency_type="wide_spread_low_liquidity",
                    severity=clamp(snap.spread / 0.20, 0, 1),
                    description=f"Spread {snap.spread:.3f} on ${snap.liquidity:.0f} liquidity",
                    detected_at=now,
                )
            )

        return inefficiencies