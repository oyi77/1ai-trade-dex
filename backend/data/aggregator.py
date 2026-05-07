"""
Multi-source data aggregator with fallback chains and caching.

Sources are registered per category (e.g. "btc_price") and tried in
priority order. A local TTL-based cache avoids redundant fetches and
provides stale data when all sources are unavailable.
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional, Any, Callable, Awaitable

from backend.core.errors import DataQualityError

logger = logging.getLogger("trading_bot.aggregator")


@dataclass
class SourceResult:
    data: Any
    source: str
    fetch_time: float  # seconds
    from_cache: bool = False


@dataclass
class DataSource:
    name: str
    fetch_fn: Callable[..., Awaitable[Any]]
    priority: int = 0  # lower = higher priority
    enabled: bool = True


class DataAggregator:
    """
    Aggregates data from multiple sources with fallback and caching.

    Usage::

        agg = DataAggregator(cache_ttl=60)
        agg.register_source("btc_price", DataSource("coinbase", fetch_coinbase, priority=0))
        agg.register_source("btc_price", DataSource("kraken",   fetch_kraken,   priority=1))
        result = await agg.fetch("btc_price")
    """

    def __init__(self, cache_ttl: float = 60.0, max_stale_age: Optional[float] = 300.0) -> None:
        self.cache_ttl = cache_ttl
        # Maximum age in seconds for stale cache to be returned (None = unlimited).
        # If all sources fail and cached data is older than this, raise DataQualityError.
        self.max_stale_age = max_stale_age
        self.sources: dict[str, list[DataSource]] = {}
        self._cache: dict[str, tuple[Any, float]] = {}  # category -> (data, timestamp)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_source(self, category: str, source: DataSource) -> None:
        """Add a source to *category*, keeping the list sorted by priority."""
        bucket = self.sources.setdefault(category, [])
        bucket.append(source)
        bucket.sort(key=lambda s: s.priority)

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    async def fetch(self, category: str, **kwargs) -> SourceResult:
        """
        Try sources in priority order for *category*.

        1. Return cached data if within TTL.
        2. Try each enabled source; on success cache and return.
        3. On total failure return stale cache (from_cache=True).
        4. If no cache exists raise DataQualityError.
        """
        # 1. Cache hit within TTL
        if category in self._cache:
            cached_data, cached_at = self._cache[category]
            age = time.monotonic() - cached_at
            if age < self.cache_ttl:
                return SourceResult(
                    data=cached_data,
                    source="cache",
                    fetch_time=0.0,
                    from_cache=True,
                )

        # 2. Try each enabled source in priority order
        for source in self.sources.get(category, []):
            if not source.enabled:
                continue
            t0 = time.monotonic()
            try:
                data = await source.fetch_fn(**kwargs)
                fetch_time = time.monotonic() - t0
                self._cache[category] = (data, time.monotonic())
                logger.debug("Fetched '%s' from source '%s' in %.3fs", category, source.name, fetch_time)
                return SourceResult(
                    data=data,
                    source=source.name,
                    fetch_time=fetch_time,
                    from_cache=False,
                )
            except Exception as exc:
                logger.warning(
                    "Source '%s' failed for category '%s': %s",
                    source.name,
                    category,
                    exc,
                )

        # 3. All sources failed — return stale cache if within max_stale_age
        if category in self._cache:
            cached_data, cached_at = self._cache[category]
            stale_age = time.monotonic() - cached_at
            if self.max_stale_age is not None and stale_age > self.max_stale_age:
                logger.warning(
                    "All sources failed for '%s'; stale cache is %.0fs old (max_stale_age=%.0fs) — rejecting.",
                    category,
                    stale_age,
                    self.max_stale_age,
                )
                raise DataQualityError(
                    f"All sources failed for category '{category}' and cached data is too stale "
                    f"({stale_age:.0f}s old, max_stale_age={self.max_stale_age:.0f}s)."
                )
            logger.warning(
                "All sources failed for '%s'; returning stale cache (age=%.0fs).",
                category,
                stale_age,
            )
            return SourceResult(
                data=cached_data,
                source="stale_cache",
                fetch_time=0.0,
                from_cache=True,
            )

        # 4. No cache — raise
        raise DataQualityError(
            f"All sources failed for category '{category}' and no cached data is available.",
        )

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def get_cache_status(self) -> dict:
        """Return age in seconds for each cached category."""
        now = time.monotonic()
        return {
            category: round(now - cached_at, 2)
            for category, (_, cached_at) in self._cache.items()
        }

    def invalidate_cache(self, category: str | None = None) -> None:
        """Clear cache for *category*, or all categories when None."""
        if category is None:
            self._cache.clear()
        else:
            self._cache.pop(category, None)
