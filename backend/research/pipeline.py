"""Self-research pipeline for PolyEdge AGI."""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import List, Tuple

import feedparser

from backend.research.models import ResearchItem

from loguru import logger

_ENTITY_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"
    ),  # "Donald Trump", "Federal Reserve"
    re.compile(r"\b([A-Z]{2,6})\b"),  # "BTC", "NFL", "NATO"
]

_MARKET_PREDICATES = {
    "mentioned_in": 0.6,
    "related_to": 0.5,
}

DEFAULT_RSS_FEEDS: list[str] | None = None


def _resolve_rss_feeds() -> list[str]:
    global DEFAULT_RSS_FEEDS
    if DEFAULT_RSS_FEEDS is not None:
        return DEFAULT_RSS_FEEDS
    try:
        from backend.config import settings

        raw = getattr(settings, "RESEARCH_RSS_FEEDS", "")
        if raw:
            DEFAULT_RSS_FEEDS = [u.strip() for u in raw.split(",") if u.strip()]
        else:
            DEFAULT_RSS_FEEDS = []
    except Exception as e:
        logger.debug("Could not resolve RSS feeds from config: %s", e)
        DEFAULT_RSS_FEEDS = []
    return DEFAULT_RSS_FEEDS


class ResearchPipeline:
    def __init__(self):
        self._seen_fingerprints: set[str] = set()

    def _fingerprint(self, title: str, source: str) -> str:
        return hashlib.sha256((title + source).encode()).hexdigest()

    async def run_research_cycle(
        self, markets: list[str] | None = None
    ) -> list[ResearchItem]:
        items: list[ResearchItem] = []

        items.extend(await self._fetch_rss_feeds())

        if markets:
            items.extend(await self._search_bigbrain(markets))

        # In-cycle dedup via fingerprint set
        deduped: list[ResearchItem] = []
        cycle_fps: set[str] = set()
        for item in items:
            if item.fingerprint not in cycle_fps:
                cycle_fps.add(item.fingerprint)
                deduped.append(item)

        scored = await self._score_items(deduped)

        result = [it for it in scored if it.relevance_score > 0.3]
        result.sort(key=lambda it: it.relevance_score, reverse=True)

        if result:
            try:
                posted = await self._post_kg_triples(result)
                if posted:
                    logger.info(
                        "KG: posted %d triples from %d research items",
                        posted,
                        len(result),
                    )
            except Exception as exc:
                logger.debug("KG posting skipped: %s", exc)

        return result

    async def _fetch_rss_feeds(self) -> list[ResearchItem]:
        from backend.config import settings

        raw = getattr(settings, "RESEARCH_RSS_FEEDS", None) or DEFAULT_RSS_FEEDS
        if isinstance(raw, str):
            feeds = [u.strip() for u in raw.split(",") if u.strip()]
        else:
            feeds = raw or []
        items: list[ResearchItem] = []

        for url in feeds:
            try:
                loop = asyncio.get_running_loop()
                feed = await loop.run_in_executor(None, feedparser.parse, url)
                for entry in feed.entries:
                    title = getattr(entry, "title", "") or ""
                    link = getattr(entry, "link", "") or ""
                    summary = (getattr(entry, "summary", "") or "")[:500]
                    source = url
                    fp = self._fingerprint(title, source)
                    items.append(
                        ResearchItem(
                            title=title,
                            source=source,
                            content=summary,
                            relevance_score=0.0,
                            url=link,
                            fingerprint=fp,
                        )
                    )
            except Exception as exc:
                logger.warning("RSS fetch failed for %s: %s", url, exc)

        return items

    async def _search_bigbrain(self, markets: list[str]) -> list[ResearchItem]:
        items: list[ResearchItem] = []
        try:
            from backend.clients.bigbrain import BigBrainClient

            brain = BigBrainClient()
            for query in markets:
                try:
                    results = await brain.search_context(query)
                    for r in results:
                        text = r.get("text", r.get("content", ""))[:500]
                        title = text[:120] if text else query
                        fp = self._fingerprint(title, "bigbrain")
                        items.append(
                            ResearchItem(
                                title=title,
                                source="bigbrain",
                                content=text,
                                relevance_score=0.0,
                                url="",
                                fingerprint=fp,
                            )
                        )
                except Exception as exc:
                    logger.warning("BigBrain search failed for '%s': %s", query, exc)
        except Exception as exc:
            logger.warning("BigBrain client init failed: %s", exc)

        return items

    # ── KG entity extraction ──────────────────────────────────────────

    def _extract_entities_regex(self, text: str) -> list[str]:
        stopwords = {
            "The",
            "This",
            "That",
            "These",
            "Those",
            "With",
            "From",
            "About",
            "After",
            "Before",
            "Under",
            "Over",
            "Into",
            "RSS",
            "URL",
            "API",
            "GET",
            "POST",
            "JSON",
            "HTML",
        }
        entities: list[str] = []
        seen: set[str] = set()
        for pattern in _ENTITY_PATTERNS:
            for match in pattern.finditer(text):
                entity = match.group(1).strip()
                words = entity.split()
                while words and words[0] in stopwords:
                    words = words[1:]
                entity = " ".join(words)
                if (
                    entity
                    and entity not in stopwords
                    and entity not in seen
                    and len(entity) > 1
                ):
                    seen.add(entity)
                    entities.append(entity)
        return entities[:20]

    async def _extract_kg_triples_llm(
        self, item: ResearchItem
    ) -> List[Tuple[str, str, str, float]]:
        try:
            from backend.ai.llm_router import LLMRouter

            router = LLMRouter()
            prompt = (
                "Extract entity relationships from this prediction-market headline.\n"
                f"Title: {item.title}\n"
                f"Content: {item.content[:300]}\n"
                'Return JSON: {"triples": [["subject", "predicate", "object", confidence_float], ...]}\n'
                "Predicates: mentioned_in, related_to, competes_with, affects, part_of.\n"
                "Max 5 triples. Confidence 0-1."
            )
            result = await router.complete_json(prompt, role="default")
            raw_triples = result.get("triples", [])
            triples: List[Tuple[str, str, str, float]] = []
            for t in raw_triples:
                if isinstance(t, (list, tuple)) and len(t) >= 3:
                    subj = str(t[0]).strip()
                    pred = str(t[1]).strip()
                    obj = str(t[2]).strip()
                    conf = float(t[3]) if len(t) > 3 else 0.7
                    conf = max(0.0, min(1.0, conf))
                    if subj and pred and obj:
                        triples.append((subj, pred, obj, conf))
            return triples[:5]
        except Exception as exc:
            logger.debug("LLM KG extraction failed, falling back to regex: %s", exc)
            return []

    async def extract_kg_triples(
        self, item: ResearchItem
    ) -> List[Tuple[str, str, str, float]]:
        triples = await self._extract_kg_triples_llm(item)
        if triples:
            return triples

        entities = self._extract_entities_regex(f"{item.title} {item.content}")
        source_label = item.source.split("/")[-1] if "/" in item.source else item.source
        market_subject = item.title[:80]

        fallback_triples: List[Tuple[str, str, str, float]] = []
        for entity in entities[:10]:
            fallback_triples.append(
                (
                    entity,
                    "mentioned_in",
                    market_subject,
                    _MARKET_PREDICATES["mentioned_in"],
                )
            )
        if source_label:
            fallback_triples.append(
                (
                    market_subject,
                    "sourced_from",
                    source_label,
                    0.8,
                )
            )
        return fallback_triples[:10]

    async def _post_kg_triples(self, items: list[ResearchItem]) -> int:
        posted = 0
        try:
            from backend.clients.bigbrain import BigBrainClient

            brain = BigBrainClient()
            for item in items:
                try:
                    triples = await self.extract_kg_triples(item)
                    for subj, pred, obj, conf in triples:
                        try:
                            result = await brain.add_kg_triple(subj, pred, obj, conf)
                            if result.get("success", False) or result.get("triple_id"):
                                posted += 1
                        except Exception as exc:
                            logger.debug("KG triple post failed: %s", exc)
                except Exception as exc:
                    logger.debug(
                        "KG extraction failed for '%s': %s", item.title[:60], exc
                    )
        except Exception as exc:
            logger.warning("BigBrainClient unavailable for KG posting: %s", exc)
        return posted

    # ── Scoring ────────────────────────────────────────────────────────

    async def _score_items(self, items: list[ResearchItem]) -> list[ResearchItem]:
        if not items:
            return items

        try:
            from backend.ai.llm_router import LLMRouter

            router = LLMRouter()
            for item in items:
                try:
                    prompt = (
                        "Rate the relevance of this headline to prediction markets "
                        "(politics, economics, crypto, sports, weather) on a 0-1 scale.\n"
                        f"Title: {item.title}\n"
                        'Respond with JSON: {"score": <float>}'
                    )
                    result = await router.complete_json(prompt, role="default")
                    score = float(result.get("score", 0.5))
                    item.relevance_score = max(0.0, min(1.0, score))
                except Exception as e:
                    logger.debug(
                        "LLM relevance scoring failed for item, defaulting to 0.5: %s",
                        e,
                    )
                    item.relevance_score = 0.5
        except Exception as exc:
            logger.warning("LLM scoring unavailable, defaulting to 0.5: %s", exc)
            for item in items:
                item.relevance_score = 0.5

        return items


# Backward-compat alias used by orchestrator, api/agents, agents/pipeline
AutonomousResearchPipeline = ResearchPipeline
