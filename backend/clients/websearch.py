"""Web Search client for PolyEdge - real-time event research for market predictions.

Multi-provider web search with configurable primary/fallback:
- Tavily API (premium, requires TAVILY_API_KEY) - best quality for research
- Exa API (neural search, requires EXA_API_KEY) - semantic understanding
- Serper API (Google SERP, requires SERPER_API_KEY) - fresh results
- DuckDuckGo HTML scraping (free, no API key) - reliable fallback

Provider selection is controlled via settings:
- WEBSEARCH_PROVIDER: Primary provider (default: "tavily")
- WEBSEARCH_FALLBACK_PROVIDER: Fallback if primary fails (default: "duckduckgo")
- Each provider requires its API key to be set (except DuckDuckGo)
"""

import httpx
import re
from dataclasses import dataclass, field
from typing import Optional, List, Literal
from datetime import datetime, timezone

from backend.config import settings

from loguru import logger

TAVILY_API_URL = settings.TAVILY_API_URL
EXA_API_URL = settings.EXA_API_URL
SERPER_API_URL = settings.SERPER_API_URL
DDG_HTML_URL = settings.DDG_HTML_URL

# Supported providers
ProviderType = Literal["tavily", "exa", "serper", "duckduckgo"]


@dataclass
class SearchResult:
    """Single search result."""

    title: str
    url: str
    content: str
    score: float = 0.0
    published_date: Optional[str] = None


@dataclass
class WebSearchResponse:
    """Aggregated search response."""

    query: str
    results: List[SearchResult] = field(default_factory=list)
    source: str = "unknown"
    searched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_context_string(self, max_results: int = 5) -> str:
        """Convert search results to a context string for AI consumption."""
        if not self.results:
            return ""

        lines = [f"[Web Search: {self.query}]"]
        for i, r in enumerate(self.results[:max_results], 1):
            snippet = r.content[:300] + "..." if len(r.content) > 300 else r.content
            lines.append(f"{i}. {r.title}: {snippet}")

        return "\n".join(lines)


class WebSearchClient:
    """Multi-provider web search client with automatic fallback."""

    def __init__(self, timeout: float = 15.0):
        from backend.config import settings

        self.settings = settings
        self.timeout = settings.WEBSEARCH_TIMEOUT_SECONDS or timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    @property
    def is_enabled(self) -> bool:
        return self.settings.WEBSEARCH_ENABLED

    def _has_api_key(self, provider: ProviderType) -> bool:
        if provider == "duckduckgo":
            return True
        if provider == "tavily":
            return bool(self.settings.TAVILY_API_KEY)
        if provider == "exa":
            return bool(self.settings.EXA_API_KEY)
        if provider == "serper":
            return bool(self.settings.SERPER_API_KEY)
        return False

    def get_active_provider(self) -> ProviderType:
        primary = self.settings.WEBSEARCH_PROVIDER.lower()
        if primary in ("tavily", "exa", "serper", "duckduckgo"):
            if self._has_api_key(primary):
                return primary
            logger.warning(
                "Primary provider '%s' missing API key, checking fallback", primary
            )

        fallback = self.settings.WEBSEARCH_FALLBACK_PROVIDER.lower()
        if fallback in ("tavily", "exa", "serper", "duckduckgo"):
            if self._has_api_key(fallback):
                return fallback

        return "duckduckgo"

    async def _search_tavily(
        self, query: str, max_results: int = 5
    ) -> WebSearchResponse:
        client = await self._get_client()
        payload = {
            "api_key": self.settings.TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "max_results": max_results,
        }

        resp = await client.post(TAVILY_API_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=item.get("score", 0.0),
                published_date=item.get("published_date"),
            )
            for item in data.get("results", [])
        ]

        return WebSearchResponse(query=query, results=results, source="tavily")

    async def _search_exa(self, query: str, max_results: int = 5) -> WebSearchResponse:
        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self.settings.EXA_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "numResults": max_results,
            "useAutoprompt": True,
            "type": "neural",
        }

        resp = await client.post(EXA_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("text", item.get("snippet", "")),
                score=item.get("score", 0.0),
                published_date=item.get("publishedDate"),
            )
            for item in data.get("results", [])
        ]

        return WebSearchResponse(query=query, results=results, source="exa")

    async def _search_serper(
        self, query: str, max_results: int = 5
    ) -> WebSearchResponse:
        client = await self._get_client()
        headers = {
            "X-API-KEY": self.settings.SERPER_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": max_results}

        resp = await client.post(SERPER_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                content=item.get("snippet", ""),
                score=1.0 - (i * 0.1),
            )
            for i, item in enumerate(data.get("organic", [])[:max_results])
        ]

        return WebSearchResponse(query=query, results=results, source="serper")

    async def _search_duckduckgo(
        self, query: str, max_results: int = 5
    ) -> WebSearchResponse:
        client = await self._get_client()

        resp = await client.post(
            DDG_HTML_URL,
            data={"q": query, "b": ""},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        resp.raise_for_status()
        results = self._parse_ddg_html(resp.text, max_results)

        return WebSearchResponse(query=query, results=results, source="duckduckgo")

    def _parse_ddg_html(self, html: str, max_results: int) -> List[SearchResult]:
        results = []
        link_pattern = re.compile(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', re.IGNORECASE
        )
        links = link_pattern.findall(html)
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL
        )

        for i, (url, title) in enumerate(links[:max_results]):
            if "uddg=" in url:
                match = re.search(r"uddg=([^&]+)", url)
                if match:
                    import urllib.parse

                    url = urllib.parse.unquote(match.group(1))

            content = ""
            if i < len(snippets):
                content = re.sub(r"<[^>]+>", "", snippets[i]).strip()

            if title.strip() and url.strip():
                results.append(
                    SearchResult(
                        title=title.strip(),
                        url=url.strip(),
                        content=content,
                        score=1.0 - (i * 0.1),
                    )
                )

        return results

    async def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        if not self.is_enabled:
            return WebSearchResponse(query=query, results=[], source="disabled")

        max_results = self.settings.WEBSEARCH_MAX_RESULTS or max_results
        provider = self.get_active_provider()

        search_methods = {
            "tavily": self._search_tavily,
            "exa": self._search_exa,
            "serper": self._search_serper,
            "duckduckgo": self._search_duckduckgo,
        }

        try:
            return await search_methods[provider](query, max_results)
        except Exception as e:
            logger.warning(f"Primary search ({provider}) failed: {e}")
            fallback = self.settings.WEBSEARCH_FALLBACK_PROVIDER.lower()
            if fallback != provider and fallback in search_methods:
                try:
                    return await search_methods[fallback](query, max_results)
                except Exception as fallback_err:
                    logger.warning(f"Fallback search ({fallback}) failed: {fallback_err}")

            if provider != "duckduckgo":
                try:
                    return await self._search_duckduckgo(query, max_results)
                except Exception as ddg_err:
                    logger.warning(f"All search providers failed. Last error: {ddg_err}")

            return WebSearchResponse(query=query, results=[], source="failed")

    async def search_for_market(self, question: str, max_results: int = 3) -> str:
        clean_query = question
        for pattern in ["Will ", "Will the ", "What will ", "?", "by ", "before "]:
            clean_query = clean_query.replace(pattern, " ")

        search_query = f"{clean_query.strip()} latest news"

        try:
            response = await self.search(search_query, max_results)
            return response.to_context_string(max_results)
        except Exception as e:
            logger.debug(f"search_for_market failed for '{question}': {e}")
            return ""

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


_websearch_instance: Optional[WebSearchClient] = None


def get_websearch() -> WebSearchClient:
    global _websearch_instance
    if _websearch_instance is None:
        _websearch_instance = WebSearchClient()
    return _websearch_instance


async def close_websearch():
    global _websearch_instance
    if _websearch_instance is not None:
        await _websearch_instance.close()
        _websearch_instance = None
