import os
import asyncio
from dotenv import load_dotenv
from data.clob_client import get_clob_client, get_market_spread

load_dotenv()

async def test():
    print("🔍 Testing Polymarket CLOB Connection...")
    client = get_clob_client()
    
    import sqlite3
    from data.storage import DB_PATH
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Check if table exists first
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_prices'")
    if not cur.fetchone():
        print("❌ table market_prices does not exist yet. Run the bot first.")
        conn.close()
        return

    cur.execute("SELECT clob_token_id, question FROM market_prices WHERE clob_token_id IS NOT NULL LIMIT 3")
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        print("❌ No clob_token_id found in database yet. Wait for bot to fetch.")
        return

    for token_id, question in rows:
        print(f"\nTarget: {question}")
        print(f"Token ID: {token_id}")
        
        spread_info = get_market_spread(client, token_id)
        if spread_info:
            print(f"✅ SUCCESS")
            print(f"   Bid: {spread_info['bid']}")
            print(f"   Ask: {spread_info['ask']}")
            print(f"   Spread: {round(spread_info['spread'], 4)}")
            print(f"   Midpoint: {round(spread_info['midpoint'], 4)}")
        else:
            print(f"❌ FAILED to fetch orderbook for {token_id}")

if __name__ == "__main__":
    asyncio.run(test())
