"""GitHub Trending Scanner — discovers new Polymarket-related repos weekly.

Scans GitHub search API for prediction market / trading bot repositories,
tracks stars/language/description, and stores discoveries in discoveries.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from loguru import logger

DISCOVERIES_PATH = Path(__file__).parent / "discoveries.json"

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"

DEFAULT_KEYWORDS = [
    "polymarket",
    "prediction market trading bot",
    "prediction market arbitrage",
    "polymarket bot",
    "prediction market strategy",
    "polymarket automated",
]


@dataclass
class RepoDiscovery:
    """A discovered GitHub repository relevant to prediction markets."""

    repo_url: str
    name: str
    full_name: str
    description: str
    language: Optional[str]
    stars: int
    forks: int
    last_updated: str
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    keywords_matched: List[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return self.full_name.lower()


def _load_discoveries(path: Path = DISCOVERIES_PATH) -> list[dict]:
    """Load existing discoveries from JSON file."""
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load discoveries from %s: %s", path, exc)
        return []


def _save_discoveries(discoveries: list[dict], path: Path = DISCOVERIES_PATH) -> None:
    """Persist discoveries to JSON file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(discoveries, f, indent=2)
    except OSError as exc:
        logger.warning("Failed to save discoveries to %s: %s", path, exc)


def _merge_discoveries(
    existing: list[dict], new_items: list[RepoDiscovery]
) -> list[dict]:
    """Merge new discoveries into existing list, deduplicating by full_name."""
    known = {d["full_name"].lower() for d in existing}
    merged = list(existing)
    added = 0
    for item in new_items:
        if item.fingerprint not in known:
            merged.append(asdict(item))
            known.add(item.fingerprint)
            added += 1
    if added:
        logger.info("GitHub scanner: added %d new repo discoveries", added)
    return merged


class GitHubScanner:
    """Scans GitHub for Polymarket-related repositories."""

    def __init__(
        self,
        keywords: Optional[List[str]] = None,
        min_stars: int = 0,
        max_results_per_keyword: int = 30,
        github_token: Optional[str] = None,
        discoveries_path: Path = DISCOVERIES_PATH,
    ):
        self.keywords = keywords or DEFAULT_KEYWORDS
        self.min_stars = min_stars
        self.max_results_per_keyword = max_results_per_keyword
        self.github_token = github_token
        self.discoveries_path = discoveries_path

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        return headers

    async def scan(self) -> List[RepoDiscovery]:
        """Run a full scan across all keywords and return new discoveries."""
        all_discovered: List[RepoDiscovery] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(timeout=30.0) as client:
            for keyword in self.keywords:
                try:
                    repos = await self._search_keyword(client, keyword)
                    for repo in repos:
                        if repo.full_name.lower() not in seen:
                            seen.add(repo.full_name.lower())
                            all_discovered.append(repo)
                    # Respect GitHub rate limits
                    await self._rate_limit_pause(client)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 403:
                        logger.warning(
                            "GitHub rate limited on keyword '%s', skipping", keyword
                        )
                    else:
                        logger.warning(
                            "GitHub search failed for '%s': %s", keyword, exc
                        )
                except Exception as exc:
                    logger.warning("GitHub search error for '%s': %s", keyword, exc)

        # Persist
        existing = _load_discoveries(self.discoveries_path)
        merged = _merge_discoveries(existing, all_discovered)
        _save_discoveries(merged, self.discoveries_path)

        logger.info(
            "GitHub scan complete: %d repos scanned, %d total in discoveries",
            len(all_discovered),
            len(merged),
        )
        return all_discovered

    async def _search_keyword(
        self, client: httpx.AsyncClient, keyword: str
    ) -> List[RepoDiscovery]:
        """Search GitHub for repos matching a single keyword."""
        params = {
            "q": f"{keyword} stars:>={self.min_stars}",
            "sort": "stars",
            "order": "desc",
            "per_page": min(self.max_results_per_keyword, 100),
        }
        resp = await client.get(
            GITHUB_SEARCH_URL, params=params, headers=self._headers()
        )
        resp.raise_for_status()
        data = resp.json()

        repos: List[RepoDiscovery] = []
        for item in data.get("items", []):
            repos.append(
                RepoDiscovery(
                    repo_url=item.get("html_url", ""),
                    name=item.get("name", ""),
                    full_name=item.get("full_name", ""),
                    description=(item.get("description") or "")[:500],
                    language=item.get("language"),
                    stars=item.get("stargazers_count", 0),
                    forks=item.get("forks_count", 0),
                    last_updated=item.get("updated_at", ""),
                    keywords_matched=[keyword],
                )
            )
        return repos

    async def _rate_limit_pause(self, client: httpx.AsyncClient) -> None:
        """Check remaining rate limit and pause if needed."""
        try:
            resp = await client.get(
                "https://api.github.com/rate_limit", headers=self._headers()
            )
            if resp.status_code == 200:
                remaining = resp.json().get("resources", {}).get("search", {}).get(
                    "remaining", 10
                )
                if remaining < 2:
                    reset_ts = (
                        resp.json()
                        .get("resources", {})
                        .get("search", {})
                        .get("reset", time.time() + 60)
                    )
                    wait = max(1, reset_ts - time.time())
                    logger.info("GitHub search rate limit low, waiting %.0fs", wait)
                    await _async_sleep(min(wait, 120))
                else:
                    await _async_sleep(2.0)
            else:
                await _async_sleep(2.0)
        except Exception:
            await _async_sleep(2.0)


async def _async_sleep(seconds: float) -> None:
    """Async sleep helper."""
    import asyncio

    await asyncio.sleep(seconds)


async def github_scan_job() -> None:
    """Scheduler entry point for weekly GitHub trending scan."""
    logger.info("Starting GitHub trending scan job")
    try:
        scanner = GitHubScanner()
        discoveries = await scanner.scan()
        logger.info("GitHub scan job complete: %d discoveries", len(discoveries))
    except Exception:
        logger.exception("GitHub scan job failed")
