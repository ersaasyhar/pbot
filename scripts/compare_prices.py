import asyncio
from data.fetcher import fetch_markets_async
from data.clob_client import get_clob_client, get_market_spread

async def compare():
    print("🔍 Comparing Gamma (Last Trade) vs CLOB (Midpoint)...")
    gamma_markets = await fetch_markets_async()
    clob = get_clob_client()
    
    # Take the top 3 high-volume markets
    for m in gamma_markets[:3]:
        token_id = m.get("clob_token_id")
        if not token_id: continue
        
        gamma_p = m["price"]
        spread_info = get_market_spread(clob, token_id)
        
        if spread_info:
            clob_p = spread_info["midpoint"]
            diff = abs(clob_p - gamma_p)
            print(f"\nMarket: {m['question'][:40]}...")
            print(f"   Gamma Price (Last Trade): {gamma_p}")
            print(f"   CLOB Price (Midpoint):   {round(clob_p, 4)}")
            print(f"   Difference:              {round(diff, 4)}")
            if diff > 0.001:
                print("   ⚠️ RESULT: CLOB is showing a more updated price than Gamma!")
        else:
            print(f"\nMarket: {m['question'][:20]}... (No CLOB data)")

if __name__ == "__main__":
    asyncio.run(compare())
