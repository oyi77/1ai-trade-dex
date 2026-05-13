import asyncio
import httpx

async def test():
    url = "https://gamma-api.polymarket.com/events"
    params = {"slug": "btc-updown-5m-1777615200"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        data = resp.json()
        if data:
            market = data[0]["markets"][0]
            print(f"Slug: {data[0]['slug']}")
            print(f"clobTokenIds: {market.get('clobTokenIds')}")
            print(f"clobTokenIds type: {type(market.get('clobTokenIds'))}")

if __name__ == "__main__":
    asyncio.run(test())
