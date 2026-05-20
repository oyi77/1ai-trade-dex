"""Tests for backend.data.aggregator — multi-source fallback and caching."""

import time
import pytest

from backend.data.aggregator import DataAggregator, DataSource, SourceResult
from backend.core.errors import DataQualityError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(
    name: str, return_value=None, raises=None, priority: int = 0
) -> DataSource:
    async def _fetch(**kwargs):
        if raises is not None:
            raise raises
        return return_value

    return DataSource(name=name, fetch_fn=_fetch, priority=priority)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_fetch_from_primary_source():
    """Primary source succeeds — result comes from it."""
    agg = DataAggregator(cache_ttl=60)
    agg.register_source(
        "price", _make_source("primary", return_value=100.0, priority=0)
    )
    agg.register_source(
        "price", _make_source("secondary", return_value=99.0, priority=1)
    )

    result = await agg.fetch("price")

    assert isinstance(result, SourceResult)
    assert result.data == 100.0
    assert result.source == "primary"
    assert result.from_cache is False


async def test_fallback_on_primary_failure():
    """Primary raises — secondary is used instead."""
    agg = DataAggregator(cache_ttl=60)
    agg.register_source(
        "price", _make_source("primary", raises=RuntimeError("down"), priority=0)
    )
    agg.register_source(
        "price", _make_source("secondary", return_value=99.0, priority=1)
    )

    result = await agg.fetch("price")

    assert result.data == 99.0
    assert result.source == "secondary"
    assert result.from_cache is False


async def test_cache_hit():
    """Second fetch within TTL returns cached data without calling sources again."""
    call_count = 0

    async def _counting_fetch(**kwargs):
        nonlocal call_count
        call_count += 1
        return 42.0

    agg = DataAggregator(cache_ttl=60)
    agg.register_source(
        "price", DataSource(name="live", fetch_fn=_counting_fetch, priority=0)
    )

    first = await agg.fetch("price")
    second = await agg.fetch("price")

    assert call_count == 1  # source called only once
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.data == 42.0
    assert second.source == "cache"


async def test_cache_stale_on_all_fail():
    """All sources fail — stale cache within max_stale_age is returned."""
    agg = DataAggregator(cache_ttl=0.01, max_stale_age=600)  # 600s max stale age
    # Seed cache with 5s-old data (within max_stale_age)
    agg._cache["price"] = (55.0, time.monotonic() - 5)

    agg.register_source(
        "price", _make_source("bad", raises=ConnectionError("offline"), priority=0)
    )

    result = await agg.fetch("price")

    assert result.from_cache is True
    assert result.data == 55.0
    assert result.source == "stale_cache"


async def test_cache_too_stale_raises():
    """All sources fail and stale cache exceeds max_stale_age — DataQualityError is raised."""
    agg = DataAggregator(cache_ttl=0.01, max_stale_age=300)
    # Seed cache with 999s-old data (exceeds max_stale_age)
    agg._cache["price"] = (55.0, time.monotonic() - 999)

    agg.register_source(
        "price", _make_source("bad", raises=ConnectionError("offline"), priority=0)
    )

    with pytest.raises(DataQualityError):
        await agg.fetch("price")


async def test_no_cache_raises():
    """All sources fail and no cache exists — DataQualityError is raised."""
    agg = DataAggregator(cache_ttl=60)
    agg.register_source(
        "price", _make_source("bad", raises=ValueError("gone"), priority=0)
    )

    with pytest.raises(DataQualityError):
        await agg.fetch("price")


async def test_register_source_ordering():
    """Sources are sorted by priority regardless of registration order."""
    agg = DataAggregator()
    agg.register_source("x", _make_source("c", priority=2))
    agg.register_source("x", _make_source("a", priority=0))
    agg.register_source("x", _make_source("b", priority=1))

    names = [s.name for s in agg.sources["x"]]
    assert names == ["a", "b", "c"]


async def test_invalidate_cache_single():
    """invalidate_cache removes only the specified category."""
    agg = DataAggregator()
    agg._cache["cat_a"] = (1, time.monotonic())
    agg._cache["cat_b"] = (2, time.monotonic())

    agg.invalidate_cache("cat_a")

    assert "cat_a" not in agg._cache
    assert "cat_b" in agg._cache


async def test_invalidate_cache_all():
    """invalidate_cache with no argument clears entire cache."""
    agg = DataAggregator()
    agg._cache["cat_a"] = (1, time.monotonic())
    agg._cache["cat_b"] = (2, time.monotonic())

    agg.invalidate_cache()

    assert agg._cache == {}


async def test_get_cache_status():
    """get_cache_status returns age in seconds per category."""
    agg = DataAggregator()
    agg._cache["price"] = (100, time.monotonic() - 5)

    status = agg.get_cache_status()

    assert "price" in status
    assert 4.5 <= status["price"] <= 6.0  # roughly 5 s old
