"""Scan GitHub for trending Polymarket-related repositories.

Uses the GitHub API to search for new or popular repos related to
Polymarket, prediction markets, and related tooling.

Usage:
    python -m backend.scripts.scan_github_trending
    python -m backend.scripts.scan_github_trending --min-stars 10 --output repos.json
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

GITHUB_API = "https://api.github.com"

SEARCH_QUERIES = [
    "polymarket",
    "prediction market trading bot",
    "polymarket clob",
    "prediction market strategy",
]


def search_repos(
    query: str, min_stars: int = 5, limit: int = 30
) -> list[dict[str, Any]]:
    """Search GitHub repos matching a query.

    Args:
        query: GitHub search query string.
        min_stars: Minimum star count filter.
        limit: Maximum results to return.

    Returns:
        List of repo info dicts.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "q": f"{query} stars:>={min_stars}",
        "sort": "updated",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    try:
        resp = httpx.get(
            f"{GITHUB_API}/search/repositories",
            params=params,
            headers=headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            logger.warning(
                "GitHub API rate limited. Set GITHUB_TOKEN for higher limits."
            )
        else:
            logger.warning("GitHub API error: {}", e)
        return []
    except Exception as e:
        logger.warning("GitHub search failed for '{}': {}", query, e)
        return []

    repos = []
    for item in data.get("items", []):
        repos.append(
            {
                "name": item["full_name"],
                "url": item["html_url"],
                "description": item.get("description", ""),
                "stars": item["stargazers_count"],
                "language": item.get("language"),
                "last_updated": item.get("updated_at"),
                "created_at": item.get("created_at"),
                "topics": item.get("topics", []),
            }
        )

    return repos


def scan_trending(
    min_stars: int = 5, limit_per_query: int = 30
) -> list[dict[str, Any]]:
    """Scan all configured queries and deduplicate results.

    Returns:
        Deduplicated list of repo dicts sorted by stars (descending).
    """
    seen = set()
    all_repos = []

    for query in SEARCH_QUERIES:
        repos = search_repos(query, min_stars=min_stars, limit=limit_per_query)
        for repo in repos:
            if repo["name"] not in seen:
                seen.add(repo["name"])
                all_repos.append(repo)

    all_repos.sort(key=lambda r: r["stars"], reverse=True)
    logger.info(
        "Found {} unique repos across {} queries", len(all_repos), len(SEARCH_QUERIES)
    )
    return all_repos


def main():
    parser = argparse.ArgumentParser(
        description="Scan GitHub for trending Polymarket repos"
    )
    parser.add_argument("--min-stars", type=int, default=5, help="Minimum star count")
    parser.add_argument("--limit", type=int, default=30, help="Results per query")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    repos = scan_trending(min_stars=args.min_stars, limit_per_query=args.limit)

    output = {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "total_repos": len(repos),
        "queries": SEARCH_QUERIES,
        "repos": repos,
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Results saved to {args.output}")
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
