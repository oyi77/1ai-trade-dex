"""BigBrain client for PolyEdge - unified memory across all apps."""

import httpx
from dataclasses import dataclass
from typing import Optional, List
from backend.config_extensions import settings

from loguru import logger


@dataclass
class BrainMemory:
    id: str
    content: str
    wing: str  # "trading", "strategy", "weather", etc.
    room: str  # subcategory
    source: str = "polyedge"


class BigBrain:
    """
    Unified brain client for PolyEdge.
    Reads from and writes to MemPalace via berkahkarya-hub API.
    """

    def __init__(self, base_url: str = None, timeout: float = 10.0):
        self.base_url = base_url or settings.BRAIN_API_URL
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def search(
        self, query: str, wing: Optional[str] = None, limit: int = 10
    ) -> List[BrainMemory]:
        """Search brain for relevant memories."""
        client = await self._get_client()
        params = {"query": query}
        if wing:
            params["wing"] = wing
        if limit is not None:
            params["limit"] = str(limit)
        try:
            resp = await client.get(f"{self.base_url}/brain/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            memories: List[BrainMemory] = []
            items = data if isinstance(data, list) else data.get("memories", [])
            for item in items:
                memories.append(
                    BrainMemory(
                        id=str(
                            item.get("id")
                            or item.get("memory_id")
                            or item.get("memoryId")
                            or item.get("memory", "")
                        ),
                        content=str(item.get("content", "")),
                        wing=str(item.get("wing", wing or "")),
                        room=str(item.get("room", "")),
                        source=str(item.get("source", "polyedge")),
                    )
                )
            return memories
        except Exception:
            # Gracefully degrade if brain service is unavailable
            logger.exception("Failed to search brain memories")
            return []

    async def _write_memory(self, wing: str, room: str, content: str) -> Optional[str]:
        client = await self._get_client()
        payload = {"wing": wing, "room": room, "content": content}
        try:
            resp = await client.post(f"{self.base_url}/brain/add", json=payload)
            resp.raise_for_status()
            data = resp.json()
            mem_id = None
            if isinstance(data, dict):
                mem_id = data.get("memoryId") or data.get("id") or data.get("memory_id")
            return mem_id
        except Exception:
            logger.exception("Failed to write memory to brain service")
            return None

    async def write_trade_outcome(self, trade_data: dict) -> Optional[str]:
        """
        Write a trade outcome to brain memory.
        trade_data contains: strategy, market, direction, pnl, edge, confidence, timestamp
        """
        direction = trade_data.get("direction", "")
        market = trade_data.get("market", trade_data.get("market_ticker", "unknown"))
        result = trade_data.get("result", "")
        pnl = trade_data.get("pnl")
        edge = trade_data.get("edge")
        strategy = trade_data.get("strategy", "")
        timestamp = trade_data.get("timestamp")
        content = f"Trade {direction} {market} {result} PnL:{pnl} edge:{edge} strategy:{strategy}"
        room = "outcomes"
        wing = "trading"
        if timestamp:
            content = f"[{timestamp}] {content}"
        return await self._write_memory(wing=wing, room=room, content=content)

    async def write_strategy_insight(
        self, strategy: str, insight: str, confidence: float
    ) -> Optional[str]:
        content = (
            f"Strategy insight: {strategy} - {insight} (confidence={confidence:.3f})"
        )
        return await self._write_memory(
            wing="trading", room="insights", content=content
        )

    async def get_trading_history(
        self, strategy: str = None, limit: int = 100
    ) -> List[dict]:
        query = ""
        if strategy:
            query = f"strategy:{strategy}"
        memories = await self.search(query=query, wing="trading", limit=limit)
        return [
            {
                "id": m.id,
                "content": m.content,
                "wing": m.wing,
                "room": m.room,
                "source": m.source,
            }
            for m in memories
        ]

    async def get_best_strategies(self) -> List[dict]:
        # Simple heuristic: fetch insights and return as a list for later ranking
        memories = await self.search(
            query="room:insights OR content:insight", wing="trading", limit=50
        )
        results = []
        for m in memories:
            results.append(
                {
                    "id": m.id,
                    "content": m.content,
                    "wing": m.wing,
                    "room": m.room,
                    "source": m.source,
                }
            )
        return results

    async def write_calibration_update(
        self, city: str, forecast: float, actual: float, error: float
    ):
        content = f"Calibration update: city={city} forecast={forecast} actual={actual} error={error}"
        return await self._write_memory(
            wing="weather", room="calibration", content=content
        )


_bigbrain_instance: Optional[BigBrain] = None


def get_bigbrain() -> BigBrain:
    global _bigbrain_instance
    if _bigbrain_instance is None:
        _bigbrain_instance = BigBrain()
    return _bigbrain_instance


async def close_bigbrain():
    global _bigbrain_instance
    if _bigbrain_instance is not None:
        await (
            _bigbrain_instance._client.aclose()
        ) if _bigbrain_instance._client else None
        _bigbrain_instance = None


class BigBrainClient(BigBrain):
    """
    Extended BigBrain client with full berkahkarya-hub capabilities.

    Adds: brain search (search_context, quick_search), Knowledge Graph
    (add_kg_triple, query_kg, kg_timeline), Agent Diary (write_diary,
    read_diary), alerts (send_alert), and health checks.

    Inherits all existing BigBrain methods unchanged.
    """

    # ── Compatibility aliases ──────────────────────────────────────────

    async def store_trade_outcome(self, trade_data: dict) -> Optional[str]:
        """Alias for write_trade_outcome (backward-compatible name)."""
        return await self.write_trade_outcome(trade_data)

    async def search_memories(
        self, query: str, wing: Optional[str] = None, limit: int = 10
    ) -> List[BrainMemory]:
        """Alias for search (backward-compatible name)."""
        return await self.search(query=query, wing=wing, limit=limit)

    # ── Brain Search ───────────────────────────────────────────────────

    async def search_context(self, query: str, limit: int = 5) -> list[dict]:
        """
        Search brain for contextual memories.

        GET /brain/search?q={query}&limit={limit}
        Returns list of result dicts with text, wing, room, similarity.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/brain/search",
                params={"q": query, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
        except Exception as e:
            logger.warning("search_context failed: %s", e)
            return []

    async def quick_search(self, query: str) -> dict:
        """
        Quick single-result brain search.

        GET /brain/quick?q={query}
        Returns the nested result dict or empty dict on failure.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/brain/quick",
                params={"q": query},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {})
        except Exception as e:
            logger.warning("quick_search failed: %s", e)
            return {}

    # ── Knowledge Graph ────────────────────────────────────────────────

    async def add_kg_triple(
        self, subject: str, predicate: str, obj: str, confidence: float = 1.0
    ) -> dict:
        """
        Add a knowledge graph triple.

        POST /brain/kg/add
        Body: {"subject", "predicate", "object", "confidence"}
        Returns response dict with success, triple_id, fact.
        """
        client = await self._get_client()
        payload = {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "confidence": confidence,
        }
        try:
            resp = await client.post(f"{self.base_url}/brain/kg/add", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("add_kg_triple failed: %s", e)
            return {"success": False, "error": str(e)}

    async def query_kg(self, entity: str) -> dict:
        """
        Query knowledge graph for an entity's facts.

        GET /brain/kg/query?entity={entity}
        Returns dict with entity, facts list, count.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/brain/kg/query",
                params={"entity": entity},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("query_kg failed: %s", e)
            return {"entity": entity, "facts": [], "count": 0}

    async def kg_timeline(self, entity: str) -> list:
        """
        Get temporal knowledge graph timeline for an entity.

        GET /brain/kg/timeline?entity={entity}
        Returns list of timeline facts.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/brain/kg/timeline",
                params={"entity": entity},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("timeline", [])
        except Exception as e:
            logger.warning("kg_timeline failed: %s", e)
            return []

    # ── Agent Diary ────────────────────────────────────────────────────

    async def write_diary(self, entry: str, topic: str = "trading") -> dict:
        """
        Write an agent diary entry.

        POST /brain/diary/write
        Body: {"agent_name": "polyedge", "entry", "topic"}
        Returns dict with success, entry_id, agent, topic, timestamp.
        """
        client = await self._get_client()
        payload = {
            "agent_name": "polyedge",
            "entry": entry,
            "topic": topic,
        }
        try:
            resp = await client.post(f"{self.base_url}/brain/diary/write", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("write_diary failed: %s", e)
            return {"success": False, "error": str(e)}

    async def read_diary(self, last_n: int = 10) -> list[dict]:
        """
        Read recent agent diary entries.

        GET /brain/diary/read?agent_name=polyedge&last_n={last_n}
        Returns list of diary entry dicts.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/brain/diary/read",
                params={"agent_name": "polyedge", "last_n": last_n},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("entries", [])
        except Exception as e:
            logger.warning("read_diary failed: %s", e)
            return []

    # ── Alerts ─────────────────────────────────────────────────────────

    async def send_alert(self, message: str, level: str = "info") -> dict:
        """
        Send an alert via berkahkarya-hub (Telegram/WhatsApp).

        POST /alert
        Body: {"message", "level"}
        Returns dict with alert_sent, results, preview.
        Falls back to local logging if hub is unreachable.
        """
        client = await self._get_client()
        payload = {"message": message, "level": level}
        try:
            resp = await client.post(f"{self.base_url}/alert", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("send_alert failed, logging locally: %s", e)
            logger.info("[ALERT:%s] %s", level.upper(), message)
            return {"alert_sent": False, "error": str(e), "logged_locally": True}

    # ── Health ─────────────────────────────────────────────────────────

    async def health(self) -> bool:
        """
        Check if berkahkarya-hub is reachable.

        GET /health
        Returns True if hub responds with HTTP 200.
        """
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.base_url}/health")
            return resp.status_code == 200
        except Exception:
            logger.exception("Failed to check brain service health")
            return False
