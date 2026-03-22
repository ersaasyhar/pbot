import asyncio
from data.fetcher import fetch_markets_async


async def main():
    markets = await fetch_markets_async()
    if markets:
        print("First market object keys:")
        print(markets[0].keys())
        print("\nFull first market object:")
        print(markets[0])


if __name__ == "__main__":
    asyncio.run(main())
