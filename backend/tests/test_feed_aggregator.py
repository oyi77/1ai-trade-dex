import pytest
from unittest.mock import patch, MagicMock
from backend.data.feed_aggregator import FeedAggregator


def _make_fake_parsed(url, entries):
    """Build a fake feedparser result."""
    parsed = MagicMock()
    parsed.feed = MagicMock()
    parsed.feed.get = lambda key, default="": "FakeSource" if key == "title" else default
    parsed.entries = entries
    return parsed


def _make_entry(title, link, summary=""):
    e = MagicMock()
    e.get = lambda key, default="": {"title": title, "link": link, "summary": summary}.get(key, default)
    e.published_parsed = None
    return e


@pytest.mark.asyncio
async def test_dedup_and_error_isolation():
    link_a = "https://example.com/article-a"
    link_b = "https://example.com/article-b"
    entry_a = _make_entry("Title A", link_a)
    entry_b = _make_entry("Title B", link_b)
    entry_a_dup = _make_entry("Title A Dup", link_a)  # same link as entry_a

    call_count = 0

    def fake_parse(url):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First feed: two entries with same link (duplicate)
            return _make_fake_parsed(url, [entry_a, entry_a_dup])
        elif call_count == 2:
            # Second feed: raises exception to test error isolation
            raise RuntimeError("feed network error")
        else:
            return _make_fake_parsed(url, [entry_b])

    aggregator = FeedAggregator(feeds=["url1", "url2", "url3"])

    with patch("feedparser.parse", side_effect=fake_parse):
        items = await aggregator.fetch_all()

    # entry_a_dup shares link with entry_a -> deduped to 1; url2 errored; url3 has entry_b
    links = [i.link for i in items]
    assert link_a in links
    assert link_b in links
    assert links.count(link_a) == 1  # no duplicates
