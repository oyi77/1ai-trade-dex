"""Feed scanning jobs — news, arbitrage, market universe."""

from loguru import logger

from backend.config import settings
from backend.core.signals import scan_universe_markets


async def news_feed_scan_job():
    """Periodically pull news feeds when NEWS_FEED_ENABLED."""
    from backend.core.scheduling.scheduler import log_event

    if not settings.NEWS_FEED_ENABLED:
        return
    try:
        from backend.data.feed_aggregator import FeedAggregator

        agg = FeedAggregator()
        items = await agg.fetch_all()
        log_event("data", f"News feed: {len(items)} items")
    except Exception as e:
        log_event("error", f"news_feed_scan error: {e}")


async def arbitrage_scan_job():
    """Periodically scan for arbitrage opportunities when ARBITRAGE_DETECTOR_ENABLED."""
    from backend.core.scheduling.scheduler import log_event

    if not settings.ARBITRAGE_DETECTOR_ENABLED:
        return
    try:
        from backend.core.arbitrage_detector import ArbitrageDetector
        from backend.core.market_scanner import fetch_all_active_markets

        markets = await fetch_all_active_markets(limit=300)
        det = ArbitrageDetector()
        market_dicts = [
            {
                "market_id": m.ticker or m.slug,
                "yes_price": m.yes_price,
                "no_price": m.no_price,
                "question": m.question,
            }
            for m in markets
        ]
        ops = det.scan_all(market_dicts)
        log_event(
            "data",
            f"Arbitrage scan: {len(ops)} opportunities from {len(market_dicts)} markets",
        )
    except Exception as e:
        log_event("error", f"arbitrage_scan error: {e}")


async def market_universe_scan_job() -> None:
    """Periodic job to refresh the universal market universe cache.

    Scans all available markets across platforms (Polymarket, Kalshi) via
    DataProvider abstraction and caches results for fast lookup by downstream
    strategies. Runs every MARKET_UNIVERSE_CACHE_TTL_SECONDS (default 300s).
    """
    from backend.core.scheduling.scheduler import log_event

    try:
        markets = await scan_universe_markets(limit=settings.AUTO_TRADER_BATCH_SIZE)
        log_event(
            "info",
            f"Universe scan: {len(markets)} markets cached",
            {"market_count": len(markets)},
        )
    except Exception as e:
        log_event("error", f"Market universe scan job failed: {e}")
        logger.exception("Error in market_universe_scan_job")
