from dataclasses import dataclass
from typing import List, Optional
import httpx
from backend.config import settings

@dataclass
class PolymeteoResolution:
    city: str
    date: str
    high_temp: float
    low_temp: float
    precipitation: float
    outcome: Optional[str] = None  # "yes" or "no" if resolved

async def fetch_polymeteo_resolutions(city: str, start_date: str, end_date: str) -> List[PolymeteoResolution]:
    api_key = getattr(settings, "POLYMETEO_API_KEY", None)
    if not api_key:
        import logging
        logging.getLogger(__name__).warning("POLYMETEO_API_KEY not set")
        return []
    api_url = getattr(settings, "POLYMETEO_API_URL", "https://api.polymeteo.com")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{api_url}/v1/resolutions",
            params={"city": city, "start_date": start_date, "end_date": end_date},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return [
                PolymeteoResolution(
                    city=r["city"],
                    date=r["date"],
                    high_temp=r["high_temp"],
                    low_temp=r["low_temp"],
                    precipitation=r["precipitation"],
                    outcome=r.get("outcome"),
                )
                for r in data.get("resolutions", [])
            ]
        return []

async def fetch_polymeteo_candles(city: str, market_id: str, timeframe: str) -> List[dict]:
    api_key = getattr(settings, "POLYMETEO_API_KEY", None)
    if not api_key:
        return []
    api_url = getattr(settings, "POLYMETEO_API_URL", "https://api.polymeteo.com")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{api_url}/v1/candles",
            params={"city": city, "market_id": market_id, "timeframe": timeframe},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("candles", [])
        return []
