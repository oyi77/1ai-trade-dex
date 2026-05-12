"""Auto-research — fetches live market context with strict timeouts."""
import asyncio
import httpx

from backend.config import settings

from loguru import logger
async def gather_market_context(market_id: str, query: str) -> str:
    """Fetch live market research context. Returns summary or 'LIVE_DATA_UNAVAILABLE' on failure."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await asyncio.wait_for(
                client.get(f"{settings.GAMMA_API_URL}/markets/{market_id}"),
                timeout=5.0
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    question = data.get("question", query)
                    volume = data.get("volume", 0)
                    liquidity = data.get("liquidity", 0)
                    return f"Market: {question}. Volume: ${volume:,.0f}. Liquidity: ${liquidity:,.0f}."
        return "LIVE_DATA_UNAVAILABLE"
    except asyncio.TimeoutError:
        return "LIVE_DATA_UNAVAILABLE"
    except Exception as e:
        logger.debug(f"Auto-research failed for {market_id}: {e}")
        return "LIVE_DATA_UNAVAILABLE"
