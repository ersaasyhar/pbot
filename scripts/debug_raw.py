import asyncio
import aiohttp
import json

BASE_URL = "https://gamma-api.polymarket.com"

async def debug_raw():
    async with aiohttp.ClientSession() as session:
        # Fetch one known slug
        slug = "btc-updown-5m-1774078500" # Updated slug (current epoch + offset)
        async with session.get(f"{BASE_URL}/events", params={"slug": slug}) as res:
            data = await res.json()
            if data and len(data) > 0:
                event = data[0]
                if "markets" in event and len(event["markets"]) > 0:
                    m = event["markets"][0]
                    print(json.dumps(m, indent=2))
            else:
                print(f"No data for slug {slug}")

if __name__ == "__main__":
    asyncio.run(debug_raw())
