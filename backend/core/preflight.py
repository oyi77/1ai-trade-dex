"""
Startup preflight checks: geoblock detection and API connectivity.
"""
import httpx

from backend.config import settings

from loguru import logger
CLOB_HOST = settings.CLOB_API_URL


async def check_geoblock() -> dict:
    """Check if this IP is geoblocked by Polymarket."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CLOB_HOST}/geoblock")
            resp.raise_for_status()
            data = resp.json()
            blocked = data.get("blocked", False)
            return {
                "blocked": blocked,
                "country": data.get("country", "unknown"),
                "status": "BLOCKED" if blocked else "OK",
            }
    except Exception as e:
        logger.warning("Geoblock check failed: %s", e)
        return {"blocked": None, "country": "unknown", "status": "CHECK_FAILED"}


async def run_preflight_checks() -> dict:
    """Run all preflight checks. Returns dict of check_name -> result."""
    results: dict = {}

    # Geoblock check
    results["geoblock"] = await check_geoblock()

    # API connectivity checks
    checks = {
        "polymarket_gamma": (f"{settings.GAMMA_API_URL}/markets?limit=1", "Gamma API"),
        "polymarket_clob": (f"{settings.CLOB_API_URL}/time", "CLOB API"),
    }

    for name, (url, label) in checks.items():
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                results[name] = {
                    "status": "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}",
                    "latency_ms": round(resp.elapsed.total_seconds() * 1000) if resp.elapsed else 0,
                }
        except Exception as e:
            results[name] = {"status": f"FAILED: {e}", "latency_ms": None}

    return results
