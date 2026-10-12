"""Thin async HTTP client for the 1ai-tracker API (sniper/wallet intelligence)."""

import httpx

from . import telegram_bot as _facade


async def tracker_get(path: str, params: dict | None = None) -> dict | None:
    """GET from tracker API. Returns parsed JSON dict or None on error."""
    base = getattr(_facade.settings, "TRACKER_API_URL", "http://127.0.0.1:4400")
    key = getattr(_facade.settings, "TRACKER_API_KEY", "")
    url = f"{base.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        _facade.logger.warning(f"tracker_get {path} failed: {exc}")
        return None
