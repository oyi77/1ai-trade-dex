import asyncio
import httpx
import sys

from backend.config import settings

async def test_modes():
    async with httpx.AsyncClient(base_url=settings.API_BASE_URL) as client:
        print("Testing mode switch...")
        
        # Test 1: Switch to paper
        r = await client.post("/api/admin/mode", json={"mode": "paper"})
        if r.status_code != 200:
            print(f"Failed to switch to paper: {r.status_code} {r.text}")
        else:
            print("✓ Switched to paper")
            
        # Test 2: Switch to testnet
        r = await client.post("/api/admin/mode", json={"mode": "testnet"})
        if r.status_code != 200:
            print(f"Failed to switch to testnet: {r.status_code} {r.text}")
        else:
            print("✓ Switched to testnet")
            
        # Test 3: Switch to live
        r = await client.post("/api/admin/mode", json={"mode": "live"})
        if r.status_code != 200:
            print(f"Failed to switch to live: {r.status_code} {r.text}")
        else:
            print("✓ Switched to live")
            
        # Check stats for live mode
        r = await client.get("/api/stats")
        if r.status_code == 200:
            data = r.json()
            print(f"Stats: {data}")
            live_stats = data.get("live", {})
            if live_stats.get("bankroll") == 100.0 and live_stats.get("total_pnl") == 0.0:
                print("✓ Live stats are clean")
            else:
                print(f"⚠️ Live stats not clean: {live_stats}")
        
        # Switch back to paper
        r = await client.post("/api/admin/mode", json={"mode": "paper"})
        print("✓ Switched back to paper")

if __name__ == "__main__":
    asyncio.run(test_modes())
