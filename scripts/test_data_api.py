import aiohttp
import asyncio
import json


async def test_data_api():
    # Use /oi endpoint
    condition_id = "0x4bbdad5d3a694ccfba49f61ea73c9c73e470a0cee59c68f5daaefa68bf4cdc68"
    url = "https://data-api.polymarket.com/oi"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params={"market": condition_id}) as res:
            if res.status == 200:
                data = await res.json()
                print("Data API Response (OI):")
                print(json.dumps(data, indent=2))
            else:
                print(f"Error: {res.status}")
                print(await res.text())


if __name__ == "__main__":
    asyncio.run(test_data_api())
