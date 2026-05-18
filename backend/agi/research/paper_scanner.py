"""Paper/Changelog Scanner — monitors Polymarket API changes and arxiv papers.

Scans Polymarket API changelog for breaking changes and arxiv for prediction
market research papers. Alerts on deprecations, new endpoints, and novel strategies.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from loguru import logger


POLYMARKET_DOCS_RSS = "https://docs.polymarket.com/changelog"
ARXIV_API_URL = "http://export.arxiv.org/api/query"

ARXIV_QUERIES = [
    "prediction market",
    "prediction market trading",
    "automated market maker",
    "polymarket",
    "information aggregation market",
]

_DEPRECATION_KEYWORDS = re.compile(
    r"\b(deprecat|remov|sunset|end.of.life|breaking.change|migration.required)\b",
    re.IGNORECASE,
)

_NEW_ENDPOINT_KEYWORDS = re.compile(
    r"\b(new.endpoint|added|new.api|new.feature|introduced|launch)\b",
    re.IGNORECASE,
)


@dataclass
class PaperAlert:
    """A discovered paper or API change worth noting."""

    title: str
    source: str  # "arxiv" or "polymarket_changelog"
    url: str
    summary: str
    alert_type: str  # "paper", "deprecation", "new_endpoint", "strategy"
    relevance: float  # 0.0 - 1.0
    published: str = ""
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            (self.title + self.source).encode()
        ).hexdigest()


def _classify_alert(title: str, summary: str) -> tuple[str, float]:
    """Classify an alert by type and estimate relevance."""
    combined = f"{title} {summary}"
    if _DEPRECATION_KEYWORDS.search(combined):
        return "deprecation", 0.9
    if _NEW_ENDPOINT_KEYWORDS.search(combined):
        return "new_endpoint", 0.8

    strategy_kw = re.compile(
        r"\b(strategy|arbitrage|market.making|trading.bot|automated|alpha|edge)\b",
        re.IGNORECASE,
    )
    if strategy_kw.search(combined):
        return "strategy", 0.7

    return "paper", 0.5


class PaperScanner:
    """Scans arxiv and Polymarket docs for relevant papers and API changes."""

    def __init__(
        self,
        arxiv_queries: Optional[List[str]] = None,
        max_results_per_query: int = 10,
    ):
        self.arxiv_queries = arxiv_queries or ARXIV_QUERIES
        self.max_results_per_query = max_results_per_query
        self._seen: set[str] = set()

    async def scan(self) -> List[PaperAlert]:
        """Run a full scan and return new alerts."""
        alerts: List[PaperAlert] = []

        alerts.extend(await self._scan_arxiv())
        alerts.extend(await self._scan_polymarket_changelog())

        # Deduplicate
        deduped: List[PaperAlert] = []
        for alert in alerts:
            if alert.fingerprint not in self._seen:
                self._seen.add(alert.fingerprint)
                deduped.append(alert)

        deduped.sort(key=lambda a: a.relevance, reverse=True)
        logger.info(
            "Paper scan complete: %d alerts (%d new)",
            len(alerts),
            len(deduped),
        )
        return deduped

    async def _scan_arxiv(self) -> List[PaperAlert]:
        """Query arxiv API for prediction market papers."""
        alerts: List[PaperAlert] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for query in self.arxiv_queries:
                try:
                    params = {
                        "search_query": f"all:{query}",
                        "start": 0,
                        "max_results": self.max_results_per_query,
                        "sortBy": "submittedDate",
                        "sortOrder": "descending",
                    }
                    resp = await client.get(ARXIV_API_URL, params=params)
                    if resp.status_code != 200:
                        continue

                    entries = self._parse_arxiv_xml(resp.text)
                    for entry in entries:
                        alert_type, relevance = _classify_alert(
                            entry.get("title", ""), entry.get("summary", "")
                        )
                        alerts.append(
                            PaperAlert(
                                title=entry.get("title", ""),
                                source="arxiv",
                                url=entry.get("link", ""),
                                summary=entry.get("summary", "")[:500],
                                alert_type=alert_type,
                                relevance=relevance,
                                published=entry.get("published", ""),
                            )
                        )
                except Exception as exc:
                    logger.warning("arxiv scan failed for '%s': %s", query, exc)

        return alerts

    def _parse_arxiv_xml(self, xml_text: str) -> list[dict]:
        """Parse arxiv Atom XML response into entry dicts."""
        import xml.etree.ElementTree as ET

        entries: list[dict] = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                link_el = entry.find("atom:link", ns)
                published_el = entry.find("atom:published", ns)
                entries.append(
                    {
                        "title": title_el.text.strip().replace("\n", " ")
                        if title_el is not None and title_el.text
                        else "",
                        "summary": summary_el.text.strip().replace("\n", " ")
                        if summary_el is not None and summary_el.text
                        else "",
                        "link": link_el.get("href", "")
                        if link_el is not None
                        else "",
                        "published": published_el.text.strip()
                        if published_el is not None and published_el.text
                        else "",
                    }
                )
        except ET.ParseError as exc:
            logger.warning("Failed to parse arxiv XML: %s", exc)
        return entries

    async def _scan_polymarket_changelog(self) -> List[PaperAlert]:
        """Check Polymarket docs for API changes (best-effort HTTP scrape)."""
        alerts: List[PaperAlert] = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://docs.polymarket.com",
                    follow_redirects=True,
                )
                if resp.status_code != 200:
                    logger.debug(
                        "Polymarket docs returned %d", resp.status_code
                    )
                    return alerts

                text = resp.text[:10000]
                if _DEPRECATION_KEYWORDS.search(text):
                    alerts.append(
                        PaperAlert(
                            title="Polymarket API deprecation detected",
                            source="polymarket_changelog",
                            url="https://docs.polymarket.com",
                            summary="Deprecation keywords found on Polymarket docs page.",
                            alert_type="deprecation",
                            relevance=0.9,
                        )
                    )
                if _NEW_ENDPOINT_KEYWORDS.search(text):
                    alerts.append(
                        PaperAlert(
                            title="Polymarket API new feature detected",
                            source="polymarket_changelog",
                            url="https://docs.polymarket.com",
                            summary="New feature/endpoints found on Polymarket docs page.",
                            alert_type="new_endpoint",
                            relevance=0.7,
                        )
                    )
        except Exception as exc:
            logger.debug("Polymarket changelog scan failed: %s", exc)

        return alerts


async def paper_scan_job() -> None:
    """Scheduler entry point for daily paper/changelog scan."""
    logger.info("Starting paper/changelog scan job")
    try:
        scanner = PaperScanner()
        alerts = await scanner.scan()
        if alerts:
            logger.info(
                "Paper scan: %d alerts (top: %s)",
                len(alerts),
                alerts[0].title[:80] if alerts else "none",
            )
        else:
            logger.info("Paper scan: no new alerts")
    except Exception:
        logger.exception("Paper scan job failed")
