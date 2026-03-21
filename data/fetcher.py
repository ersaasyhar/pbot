import asyncio
import aiohttp
import time
import json

BASE_URL = "https://gamma-api.polymarket.com"

COINS = ["btc", "eth", "sol", "doge", "bnb", "xrp"]
TIMEFRAMES = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}

MAX_RETRIES = 3

# ---------------------------
# TIME HELPERS
# ---------------------------
def get_epoch(tf_seconds):
    now = int(time.time())
    return now - (now % tf_seconds)

# ---------------------------
# SLUG GENERATION
# ---------------------------
def generate_candidate_slugs():
    candidates = []
    for coin in COINS:
        for tf, seconds in TIMEFRAMES.items():
            current_epoch = get_epoch(seconds)
            prev_epoch = current_epoch - seconds
            candidates.append((coin, tf, f"{coin}-updown-{tf}-{current_epoch}"))
            candidates.append((coin, tf, f"{coin}-updown-{tf}-{prev_epoch}"))
    return candidates

# ---------------------------
# ASYNC REQUEST WITH RETRY
# ---------------------------
async def safe_get(session, url, params):
    for _ in range(MAX_RETRIES):
        try:
            async with session.get(url, params=params, timeout=10) as res:
                if res.status == 200:
                    return await res.json()
        except:
            await asyncio.sleep(1)
    return None

# ---------------------------
# FETCH SINGLE EVENT
# ---------------------------
async def fetch_event(session, coin, tf, slug):
    data = await safe_get(session, f"{BASE_URL}/events", {"slug": slug})
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    return (coin, tf, data[0])

# ---------------------------
# PARSE MARKET
# ---------------------------
def parse_market(event, coin, timeframe):
    markets = []
    for m in event.get("markets", []):
        if not m.get("active") or m.get("closed"):
            continue

        price = m.get("lastTradePrice")
        if not price:
            op = m.get("outcomePrices")
            if isinstance(op, str):
                try: op = json.loads(op)
                except: op = None
            if isinstance(op, list) and len(op) > 0:
                try: price = float(op[0])
                except: price = None

        if price is None or price <= 0 or price > 1:
            continue

        # Parse clobTokenIds (JSON string list)
        ctids_raw = m.get("clobTokenIds")
        clob_token_id = None
        if ctids_raw:
            try:
                ctids = json.loads(ctids_raw)
                if isinstance(ctids, list) and len(ctids) > 0:
                    clob_token_id = str(ctids[0])
            except:
                pass

        markets.append({
            "market_id": str(m.get("id")),
            "condition_id": m.get("conditionId"),
            "clob_token_id": clob_token_id,
            "question": m.get("question", f"{coin.upper()} {timeframe}"),
            "price": float(price),
            "volume": float(m.get("volumeNum") or 0),
            "coin": coin,
            "timeframe": timeframe,
            "timestamp": int(time.time())
        })
    return markets

# ---------------------------
# MAIN ASYNC FETCHER
# ---------------------------
async def fetch_markets_async():
    all_markets = []
    seen = set()
    candidates = generate_candidate_slugs()

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_event(session, coin, tf, slug) for coin, tf, slug in candidates]
        results = await asyncio.gather(*tasks)

        for result in results:
            if not result: continue
            coin, tf, event = result
            key = f"{coin}-{tf}"
            if key in seen: continue

            markets = parse_market(event, coin, tf)
            if markets:
                all_markets.extend(markets)
                seen.add(key)

    all_markets.sort(key=lambda x: x["volume"], reverse=True)
    return all_markets

if __name__ == "__main__":
    res = asyncio.run(fetch_markets_async())
    for m in res:
        print(f"[{m['coin']}-{m['timeframe']}] {m['price']} | Vol: {m['volume']} | {m['question']}")