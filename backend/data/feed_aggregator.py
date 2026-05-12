"""RSS news feed aggregation for sentiment signals."""
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from backend.config import settings

from loguru import logger
DEFAULT_FEEDS = [
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://cointelegraph.com/rss",
    "https://coindesk.com/arc/outboundfeeds/rss/",
]


def _resolve_feeds() -> List[str]:
    configured = getattr(settings, "RSS_FEED_URLS", "")
    if configured:
        return [u.strip() for u in configured.split(",") if u.strip()]
    return list(DEFAULT_FEEDS)


@dataclass
class NewsItem:
    source: str
    title: str
    link: str
    published_at: Optional[datetime]
    summary: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(self.link.encode()).hexdigest()


class FeedAggregator:
    def __init__(self, feeds: Optional[List[str]] = None):
        self.feeds = feeds or _resolve_feeds()

    async def fetch_all(self) -> List[NewsItem]:
        tasks = [self._fetch_one(url) for url in self.feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        items: List[NewsItem] = []
        seen = set()
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"feed error: {r}")
                continue
            for item in r:
                if item.fingerprint in seen:
                    continue
                seen.add(item.fingerprint)
                items.append(item)
        return items

    async def _fetch_one(self, url: str) -> List[NewsItem]:
        import feedparser
        loop = asyncio.get_event_loop()
        parsed = await loop.run_in_executor(None, feedparser.parse, url)
        out = []
        for entry in parsed.entries[:50]:
            try:
                pub = None
                if getattr(entry, "published_parsed", None):
                    pub = datetime(*entry.published_parsed[:6])
                out.append(NewsItem(
                    source=parsed.feed.get("title", url),
                    title=entry.get("title", ""),
                    link=entry.get("link", ""),
                    published_at=pub,
                    summary=entry.get("summary", ""),
                ))
            except Exception as e:
                logger.debug(f"entry parse failed: {e}")
        return out
