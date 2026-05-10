"""bk-brain integration — cross-ecosystem memory sharing. Async, non-blocking."""
import logging
import httpx
import os

from backend.config import settings

logger = logging.getLogger("trading_bot.bk_brain")

BK_BRAIN_URL = os.getenv("BK_BRAIN_URL", "http://localhost:9099")
BK_BRAIN_ENABLED = os.getenv("BK_BRAIN_ENABLED", "false").lower() == "true"


async def store_memory(title: str, content: str, tags: list = None) -> bool:
    """Store a memory in bk-brain. Non-blocking — returns False silently on failure."""
    if not BK_BRAIN_ENABLED:
        return False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{BK_BRAIN_URL}/brain/remember",
                json={"content": content, "title": title, "tags": tags or []},
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to store memory in bk-brain: {e}")
        return False


async def search_memory(query: str, limit: int = 5) -> list:
    """Search bk-brain for relevant memories."""
    if not BK_BRAIN_ENABLED:
        return []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{BK_BRAIN_URL}/brain/search",
                json={"query": query, "limit": limit},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", [])[:limit]
    except Exception as e:
        logger.error(f"Failed to search memory in bk-brain: {e}")
    return []
