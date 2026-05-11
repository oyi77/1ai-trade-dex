"""Smoke test: verify the market scanner can fetch real markets."""
import asyncio
import sys
sys.path.insert(0, ".")

from backend.core.market_scanner import fetch_all_active_markets, fetch_markets_by_keywords

async def main():
    print("Fetching active markets (up to 200)...")
    markets = await fetch_all_active_markets(limit=200)
    print(f"Got {len(markets)} markets")
    assert len(markets) > 0, "Expected at least 1 market"

    print("Fetching BTC markets...")
    btc = await fetch_markets_by_keywords(["btc", "bitcoin"], limit=500)
    print(f"BTC markets: {len(btc)}")

    print("Fetching weather markets...")
    wx = await fetch_markets_by_keywords(["temperature", "weather", "degrees"], limit=500)
    print(f"Weather markets: {len(wx)}")

    print("SMOKE TEST PASSED")

if __name__ == "__main__":
    asyncio.run(main())
