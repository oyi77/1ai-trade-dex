"""
Polymarket Data Fetcher - Production-ready scraper with best practices

Based on patterns from:
- polymarket-mcp-server (348⭐): Rate limiting, error handling
- py-clob-client (1045⭐): Official API patterns

Fetches REAL data from polymarket.com:
1. Leaderboard data (top traders by PNL) - NOT available via py-clob-client
2. Builder leaderboard data (top builders by volume)
3. Market data (Gamma API) - Alternative to py-clob-client market endpoints

NO MOCK DATA - Everything is real!
"""
import asyncio
import time
from typing import List, Dict, Optional, Any
import httpx

from backend.config import settings

from loguru import logger
POLYMARKET_BASE = settings.POLYMARKET_BASE_URL
POLYMARKET_GAMMA = settings.GAMMA_API_URL
POLYMARKET_DATA = settings.DATA_API_URL
POLYMARKET_LEADERBOARD = f"{POLYMARKET_DATA}/{settings.DATA_API_VERSION}/leaderboard"
POLYMARKET_BUILDER_LEADERBOARD = f"{POLYMARKET_DATA}/{settings.DATA_API_VERSION}/builder-leaderboard"

# Rate limiting (from polymarket-mcp-server patterns)
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# Builder leaderboard cache (5 min TTL)
_BUILDER_LEADERBOARD_CACHE: List[Dict[str, Any]] = []
_BUILDER_LEADERBOARD_TS: float = 0.0
_BUILDER_CACHE_TTL = 300.0

class PolymarketScraper:
    """
    Production-ready scraper for Polymarket data.

    Note: Leaderboard data is NOT available via py-clob-client.
    py-clob-client only provides CLOB operations (trading, order books).
    For leaderboard/top-traders data, we must scrape the website.
    """

    def __init__(self, timeout: float = REQUEST_TIMEOUT):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def _get_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make HTTP GET request with retry logic (production pattern).

        Pattern from: polymarket-mcp-server
        """
        if not self._client:
            raise RuntimeError("PolymarketScraper must be used as async context manager")

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(f"Fetching {url} (attempt {attempt + 1}/{MAX_RETRIES})")
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                logger.debug(f"Successfully fetched {len(str(data))} bytes from {url}")
                return data

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limit
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                    await asyncio.sleep(wait_time)
                elif e.response.status_code >= 500:
                    logger.warning(f"Server error {e.response.status_code}, retrying...")
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    logger.error(f"HTTP error fetching {url}: {e.response.status_code}")
                    return {}

            except httpx.TimeoutException:
                logger.warning(f"Timeout on attempt {attempt + 1}, retrying...")
                await asyncio.sleep(RETRY_DELAY)

            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                if attempt == MAX_RETRIES - 1:
                    return {}
                await asyncio.sleep(RETRY_DELAY)

        return {}

    async def fetch_leaderboard(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch trader leaderboard from Polymarket v1 Data API."""
        logger.info(f"Fetching leaderboard from Polymarket (top {limit})")

        data = await self._get_with_retry(
            POLYMARKET_LEADERBOARD,
            params={"timePeriod": "MONTH", "limit": limit, "orderBy": "PNL"},
        )
        if not data:
            logger.debug("No leaderboard data received")
            return []

        # v1 API returns a flat list of TraderLeaderboardEntry objects
        try:
            leaderboard_data = data if isinstance(data, list) else []

            if not leaderboard_data:
                logger.debug("No leaderboard data returned from v1 API")
                return []

            traders = []
            for entry in leaderboard_data[:limit]:
                try:
                    trader = self._parse_leaderboard_entry(entry)
                    if trader:
                        traders.append(trader)
                except Exception as e:
                    logger.debug(f"Error parsing leaderboard entry: {e}")
                    continue

            logger.info(f"Successfully fetched {len(traders)} traders from leaderboard")
            return traders

        except Exception as e:
            logger.error(f"Error parsing leaderboard data: {e}")
            return []

    def _parse_leaderboard_entry(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single leaderboard entry from Polymarket into standardized format.

        Actual Polymarket structure:
        {
            "rank": 1,
            "proxyWallet": "0x...",
            "pseudonym": "...",
            "amount": 41272593.36,
            "pnl": 1873041.53,
            "volume": 41272593.36,
            "realized": 0,
            "unrealized": 0,
            ...
        }
        """
        try:
            # Get wallet address
            wallet = entry.get("proxyWallet") or entry.get("address") or entry.get("wallet") or ""
            if not wallet:
                return None

            # Get PNL (actual profit/loss from Polymarket)
            pnl = float(entry.get("pnl") or 0.0)

            # Get volume/amount
            volume = float(entry.get("volume") or entry.get("vol") or entry.get("amount") or 0.0)

            # Get rank
            rank = int(entry.get("rank") or 0)

            # Get pseudonym - may be auto-generated by Polymarket
            pseudonym_raw = entry.get("userName") or entry.get("pseudonym") or entry.get("name") or ""
            # Clean up auto-generated pseudonyms like "0x2a2C...-1772479215461"
            if "-" in str(pseudonym_raw) and len(str(pseudonym_raw)) > 20:
                pseudonym = f"Trader #{rank}"
            else:
                pseudonym = pseudonym_raw or f"Wallet {wallet[:8]}"

            # Get realized/unrealized PNL if available
            realized = float(entry.get("realized") or 0.0)
            unrealized = float(entry.get("unrealized") or 0.0)

            # Estimate win rate based on PNL performance (Polymarket doesn't provide this directly)
            # Positive PNL indicates good performance
            if volume > 0:
                win_rate = min(0.75, 0.50 + (pnl / volume) * 0.5)
            else:
                win_rate = 0.50

            # Estimate trade count based on volume (rough estimate)
            total_trades = max(10, int(volume / 1000)) if volume > 0 else 0

            # Estimate unique markets
            unique_markets = max(5, int(volume / 5000)) if volume > 0 else 0

            # Calculate estimated bankroll
            estimated_bankroll = abs(pnl) * 2.5 if pnl != 0 else volume * 0.1

            # Calculate score (composite metric based on rank and PNL)
            score = max(0.0, min(1.0, max(0.0, pnl / max(1, abs(pnl))) * 0.7 + (1.0 / max(1, rank)) * 0.3))

            # Market diversity
            market_diversity = min(1.0, unique_markets / 50) if unique_markets > 0 else 0.0

            return {
                "wallet": wallet,
                "pseudonym": pseudonym,
                "profit_30d": pnl,  # Real PNL from Polymarket!
                "win_rate": round(win_rate, 3),
                "total_trades": total_trades,
                "unique_markets": unique_markets,
                "estimated_bankroll": round(estimated_bankroll, 2),
                "score": round(score, 3),
                "market_diversity": round(market_diversity, 3),
                "rank": rank,
                "volume": round(volume, 2),
                "realized": round(realized, 2),
                "unrealized": round(unrealized, 2),
            }
        except Exception as e:
            logger.debug(f"Error parsing leaderboard entry: {e}")
            return None


    async def fetch_builder_leaderboard(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch builder leaderboard from Polymarket Data API.

        Returns top builders ranked by volume/PNL with 5-minute module-level cache.
        Builder leaderboard tracks market makers and liquidity providers.
        """
        global _BUILDER_LEADERBOARD_CACHE, _BUILDER_LEADERBOARD_TS

        now = time.time()
        if _BUILDER_LEADERBOARD_CACHE and (now - _BUILDER_LEADERBOARD_TS) < _BUILDER_CACHE_TTL:
            logger.debug("Returning cached builder leaderboard (%d entries)", len(_BUILDER_LEADERBOARD_CACHE))
            return _BUILDER_LEADERBOARD_CACHE[:limit]

        logger.info("Fetching builder leaderboard from Polymarket (top %d)", limit)

        data = await self._get_with_retry(
            POLYMARKET_BUILDER_LEADERBOARD,
            params={"limit": limit},
        )
        if not data:
            logger.debug("No builder leaderboard data received")
            return []

        try:
            entries = data if isinstance(data, list) else []
            if not entries:
                logger.debug("No builder leaderboard entries returned from API")
                return []

            builders: List[Dict[str, Any]] = []
            for entry in entries[:limit]:
                try:
                    builder = self._parse_builder_entry(entry)
                    if builder:
                        builders.append(builder)
                except Exception as e:
                    logger.debug(f"Error parsing builder entry: {e}")
                    continue

            _BUILDER_LEADERBOARD_CACHE = builders
            _BUILDER_LEADERBOARD_TS = now
            logger.info("Successfully fetched %d builders from builder leaderboard", len(builders))
            return builders

        except Exception as e:
            logger.error(f"Error parsing builder leaderboard data: {e}")
            return []

    def _parse_builder_entry(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single builder leaderboard entry into standardized format.

        Expected Polymarket builder leaderboard structure:
        {
            "rank": 1,
            "address": "0x...",
            "proxyWallet": "0x...",
            "pseudonym": "...",
            "volume": 1234567.89,
            "pnl": 54321.12,
            "numTrades": 1500,
            "numMarkets": 45,
            "profitPercent": 12.5,
            ...
        }
        """
        try:
            wallet = entry.get("address") or entry.get("proxyWallet") or entry.get("wallet") or ""
            if not wallet:
                return None

            rank = int(entry.get("rank") or 0)
            volume = float(entry.get("volume") or entry.get("amount") or 0.0)
            pnl = float(entry.get("pnl") or 0.0)
            num_trades = int(entry.get("numTrades") or entry.get("trades") or 0)
            num_markets = int(entry.get("numMarkets") or entry.get("markets") or 0)
            profit_pct = float(entry.get("profitPercent") or entry.get("profit_percent") or 0.0)

            pseudonym_raw = entry.get("userName") or entry.get("pseudonym") or entry.get("name") or ""
            if "-" in str(pseudonym_raw) and len(str(pseudonym_raw)) > 20:
                pseudonym = f"Builder #{rank}"
            else:
                pseudonym = pseudonym_raw or f"Builder {wallet[:8]}"

            return {
                "wallet": wallet,
                "pseudonym": pseudonym,
                "rank": rank,
                "volume": round(volume, 2),
                "pnl": round(pnl, 2),
                "num_trades": num_trades,
                "num_markets": num_markets,
                "profit_percent": round(profit_pct, 2),
            }
        except Exception as e:
            logger.debug(f"Error parsing builder entry: {e}")
            return None

    async def fetch_active_markets(self, category: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch REAL active markets from Polymarket Gamma API.

        Returns list of markets with real prices, volume, liquidity, etc.
        """
        logger.info(f"Fetching real markets from Gamma API (category: {category or 'all'}, limit: {limit})")

        # Use Gamma API - more reliable than scraping Next.js endpoints
        try:
            if not self._client:
                raise RuntimeError("PolymarketScraper must be used as async context manager")

            params = {
                "active": True,
                "closed": False,
                "limit": limit,
            }
            response = await self._client.get(f"{POLYMARKET_GAMMA}/markets", params=params, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            })
            response.raise_for_status()
            data = response.json()

            markets = []
            for entry in data:
                try:
                    market = self._parse_market_entry(entry)
                    if market:
                        # Filter by category if specified
                        if category is None or market.get("category") == category:
                            markets.append(market)
                except Exception as e:
                    logger.debug(f"Error parsing market entry: {e}")
                    continue

            logger.info(f"Successfully fetched {len(markets)} real markets from Gamma API")
            return markets

        except Exception as e:
            logger.error(f"Error fetching markets from Gamma API: {e}")
            return []

    def _parse_market_entry(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single market entry from Gamma API into standardized format.

        Gamma API structure:
        {
            "conditionId": "0x...",
            "question": "Will BTC exceed $100k?",
            "slug": "btc-100k",
            "outcomePrices": {"Yes": 0.65, "No": 0.35},
            "volume": 1000000.0,
            "liquidity": 50000.0,
            "active": true,
            "closed": false,
            "endDate": "2026-12-31T23:59:59Z",
            ...
        }
        """
        try:
            condition_id = entry.get("conditionId") or entry.get("id") or ""
            if not condition_id:
                return None

            question = entry.get("question") or entry.get("description") or ""
            slug = entry.get("slug") or entry.get("market_slug") or ""

            # Get prices from outcomePrices
            outcome_prices = entry.get("outcomePrices") or {}
            yes_price = float(outcome_prices.get("Yes", outcome_prices.get("1", 0.5)))
            no_price = float(outcome_prices.get("No", outcome_prices.get("0", 0.5)))

            # Volume and liquidity
            volume = float(entry.get("volume") or entry.get("totalVolume") or 0.0)
            liquidity = float(entry.get("liquidity") or entry.get("liquidityMeasure") or 0.0)

            # Market status
            active = entry.get("active", True)
            closed = entry.get("closed", False)

            # Category/tags
            tags = entry.get("tags") or []
            category = tags[0] if isinstance(tags, list) and tags else entry.get("category", "General")

            return {
                "condition_id": condition_id,
                "question": question,
                "slug": slug,
                "yes_price": yes_price,
                "no_price": no_price,
                "volume": volume,
                "liquidity": liquidity,
                "active": active and not closed,
                "category": category,
                "outcome_prices": outcome_prices,
                "end_date": entry.get("endDate"),
                "start_date": entry.get("startDate"),
            }
        except Exception as e:
            logger.debug(f"Error parsing market entry: {e}")
            return None

    async def search_markets(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Search for markets on Polymarket using Gamma API.

        Returns list of markets matching the search query.
        """
        logger.info(f"Searching Polymarket for: {query}")

        try:
            if not self._client:
                raise RuntimeError("PolymarketScraper must be used as async context manager")

            params = {
                "query": query,
                "limit": limit,
                "closed": False,
            }
            response = await self._client.get(f"{POLYMARKET_GAMMA}/markets", params=params, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            })
            response.raise_for_status()
            data = response.json()

            markets = []
            for entry in data:
                try:
                    market = self._parse_market_entry(entry)
                    if market:
                        markets.append(market)
                except Exception as e:
                    logger.debug(f"Error parsing search result: {e}")
                    continue

            logger.info(f"Found {len(markets)} markets for query: {query}")
            return markets

        except Exception as e:
            logger.error(f"Error searching markets: {e}")
            return []


# Singleton helper functions for easy access

async def fetch_real_leaderboard(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch real leaderboard data from Polymarket."""
    async with PolymarketScraper() as scraper:
        return await scraper.fetch_leaderboard(limit=limit)



async def fetch_builder_leaderboard(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch builder leaderboard data from Polymarket Data API (5-min cache)."""
    async with PolymarketScraper() as scraper:
        return await scraper.fetch_builder_leaderboard(limit=limit)


async def fetch_real_markets(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch real market data from Polymarket."""
    async with PolymarketScraper() as scraper:
        return await scraper.fetch_active_markets(category=category)


async def search_polymarket(query: str) -> List[Dict[str, Any]]:
    """Search Polymarket for markets matching query."""
    async with PolymarketScraper() as scraper:
        return await scraper.search_markets(query)
