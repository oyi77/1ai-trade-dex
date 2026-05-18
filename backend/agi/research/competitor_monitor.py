"""Competitor Strategy Monitor — tracks competitor repos for strategy changes.

Monitors known prediction market bot repos for new commits, strategy changes,
and win rate claims. Extracts strategy patterns worth adopting.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from loguru import logger

COMPETITOR_DB_PATH = Path(__file__).parent / "competitor_state.json"

GITHUB_API = "https://api.github.com"

DEFAULT_COMPETITORS = [
    "4coinsbot",
    "polyrec",
    "polymarket-btc-autotrader",
    "PolyHFT",
]

# GitHub search queries to find competitor repos
COMPETITOR_SEARCH_QUERIES = [
    "polymarket trading bot",
    "polymarket arbitrage bot",
    "prediction market bot",
]


@dataclass
class CompetitorRepo:
    """A tracked competitor repository."""

    full_name: str
    repo_url: str
    description: str
    stars: int
    language: Optional[str]
    last_commit_sha: str
    last_commit_msg: str
    last_checked: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    strategy_signals: List[str] = field(default_factory=list)


@dataclass
class CompetitorChange:
    """A detected change in a competitor repo."""

    repo_full_name: str
    change_type: str  # "new_commits", "strategy_change", "win_rate_claim"
    summary: str
    details: str
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    relevance: float = 0.5

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            (self.repo_full_name + self.summary).encode()
        ).hexdigest()


def _load_state(path: Path = COMPETITOR_DB_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict, path: Path = COMPETITOR_DB_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as exc:
        logger.warning("Failed to save competitor state: %s", exc)


_STRATEGY_KEYWORDS = {
    "arbitrage",
    "market making",
    "frontrun",
    "scalping",
    "oracle",
    "momentum",
    "mean reversion",
    "sentiment",
    "whale",
    "copy trade",
    "automated",
    "backtest",
    "win rate",
    "profit",
    "edge",
    "alpha",
}


def _extract_strategy_signals(text: str) -> List[str]:
    """Extract strategy-related keywords from commit message or description."""
    text_lower = text.lower()
    return [kw for kw in _STRATEGY_KEYWORDS if kw in text_lower]


class CompetitorMonitor:
    """Monitors competitor GitHub repos for strategy changes."""

    def __init__(
        self,
        competitors: Optional[List[str]] = None,
        github_token: Optional[str] = None,
        state_path: Path = COMPETITOR_DB_PATH,
    ):
        self.competitors = competitors or DEFAULT_COMPETITORS
        self.github_token = github_token
        self.state_path = state_path

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        return headers

    async def monitor(self) -> List[CompetitorChange]:
        """Run a full monitoring cycle and return detected changes."""
        state = _load_state(self.state_path)
        changes: List[CompetitorChange] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Resolve competitor repos (by name search)
            for competitor in self.competitors:
                try:
                    repo_info = await self._resolve_repo(client, competitor)
                    if repo_info is None:
                        continue

                    full_name = repo_info["full_name"]
                    prev = state.get(full_name, {})
                    detected = await self._check_repo(
                        client, repo_info, prev
                    )
                    changes.extend(detected)

                    # Update state
                    state[full_name] = {
                        "full_name": full_name,
                        "repo_url": repo_info.get("html_url", ""),
                        "description": repo_info.get("description", ""),
                        "stars": repo_info.get("stargazers_count", 0),
                        "language": repo_info.get("language"),
                        "last_commit_sha": detected[0].summary.split(":")[0]
                        if detected and detected[0].change_type == "new_commits"
                        else prev.get("last_commit_sha", ""),
                        "last_checked": datetime.now(timezone.utc).isoformat(),
                    }
                except Exception as exc:
                    logger.warning(
                        "Competitor monitor failed for '%s': %s", competitor, exc
                    )

        _save_state(state, self.state_path)
        logger.info(
            "Competitor monitor: %d changes detected across %d repos",
            len(changes),
            len(self.competitors),
        )
        return changes

    async def _resolve_repo(
        self, client: httpx.AsyncClient, name: str
    ) -> Optional[dict]:
        """Resolve a competitor name to a GitHub repo dict."""
        # Try direct repo lookup first (org/name format)
        if "/" in name:
            try:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{name}", headers=self._headers()
                )
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                pass

        # Search by name
        try:
            resp = await client.get(
                f"{GITHUB_API}/search/repositories",
                params={"q": name, "per_page": 5, "sort": "stars"},
                headers=self._headers(),
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    return items[0]
        except Exception as exc:
            logger.debug("Repo resolution failed for '%s': %s", name, exc)
        return None

    async def _check_repo(
        self,
        client: httpx.AsyncClient,
        repo_info: dict,
        prev_state: dict,
    ) -> List[CompetitorChange]:
        """Check a single repo for changes since last check."""
        changes: List[CompetitorChange] = []
        full_name = repo_info["full_name"]
        prev_sha = prev_state.get("last_commit_sha", "")

        # Fetch recent commits
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/commits",
                params={"per_page": 10},
                headers=self._headers(),
            )
            if resp.status_code == 200:
                commits = resp.json()
                new_commits = []
                for commit in commits:
                    sha = commit.get("sha", "")
                    if sha == prev_sha:
                        break
                    new_commits.append(commit)

                if new_commits:
                    # Analyze commit messages for strategy signals
                    for commit in new_commits[:5]:
                        msg = commit.get("commit", {}).get("message", "")
                        signals = _extract_strategy_signals(msg)
                        if signals:
                            changes.append(
                                CompetitorChange(
                                    repo_full_name=full_name,
                                    change_type="strategy_change",
                                    summary=f"{commit.get('sha', '')[:7]}: {msg[:100]}",
                                    details=f"Strategy signals: {', '.join(signals)}",
                                    relevance=0.7,
                                )
                            )

                    if new_commits and not any(
                        c.change_type == "strategy_change" for c in changes
                    ):
                        changes.append(
                            CompetitorChange(
                                repo_full_name=full_name,
                                change_type="new_commits",
                                summary=f"{len(new_commits)} new commits",
                                details=new_commits[0]
                                .get("commit", {})
                                .get("message", "")[:200],
                                relevance=0.4,
                            )
                        )
        except Exception as exc:
            logger.debug("Commit check failed for %s: %s", full_name, exc)

        # Check README for win rate claims
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/readme",
                headers=self._headers(),
            )
            if resp.status_code == 200:
                import base64

                content = base64.b64decode(
                    resp.json().get("content", "")
                ).decode("utf-8", errors="replace")
                win_rate_signals = _extract_strategy_signals(content)
                if "win rate" in win_rate_signals or "profit" in win_rate_signals:
                    changes.append(
                        CompetitorChange(
                            repo_full_name=full_name,
                            change_type="win_rate_claim",
                            summary="Win rate / profit claim in README",
                            details=content[:300],
                            relevance=0.8,
                        )
                    )
        except Exception:
            pass

        return changes


async def competitor_monitor_job() -> None:
    """Scheduler entry point for weekly competitor monitoring."""
    logger.info("Starting competitor monitor job")
    try:
        monitor = CompetitorMonitor()
        changes = await monitor.monitor()
        logger.info("Competitor monitor job complete: %d changes", len(changes))
    except Exception:
        logger.exception("Competitor monitor job failed")
