import asyncio
import aiohttp
import time
import json
from app.config import ACTIVE_COINS
from app.logger import get_logger

BASE_URL = "https://gamma-api.polymarket.com"

COINS = ACTIVE_COINS
TIMEFRAMES = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}

MAX_RETRIES = 3
logger = get_logger()


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
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, params=params, timeout=10) as res:
                if res.status == 200:
                    return await res.json()
                if attempt == MAX_RETRIES:
                    logger.warning(
                        f"safe_get failed status={res.status} after {MAX_RETRIES} attempts url={url} params={params}"
                    )
        except Exception as e:
            if attempt == MAX_RETRIES:
                logger.warning(
                    f"safe_get exception={type(e).__name__} after {MAX_RETRIES} attempts "
                    f"url={url} params={params}"
                )
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
def parse_market(event, coin, timeframe, tf_seconds):
    markets = []
    for m in event.get("markets", []):
        if not m.get("active") or m.get("closed"):
            continue

        def parse_jsonish(value):
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    return parsed if isinstance(parsed, list) else None
                except Exception:
                    return None
            return None

        outcomes = parse_jsonish(m.get("outcomes")) or []
        outcome_prices = parse_jsonish(m.get("outcomePrices")) or []
        clob_ids = parse_jsonish(m.get("clobTokenIds")) or []

        # Pick the YES side consistently (for crypto up/down this is "Up").
        yes_aliases = {"yes", "up", "higher", "above", "true"}
        no_aliases = {"no", "down", "lower", "below", "false"}
        chosen_idx = None
        for i, name in enumerate(outcomes):
            if str(name).strip().lower() in yes_aliases:
                chosen_idx = i
                break
        if chosen_idx is None and outcomes:
            # If we can identify NO side, derive YES price from 1-NO.
            for i, name in enumerate(outcomes):
                if str(name).strip().lower() in no_aliases and i < len(outcome_prices):
                    try:
                        no_px = float(outcome_prices[i])
                        if 0 < no_px < 1:
                            chosen_idx = i
                    except Exception:
                        pass
                    break
        if chosen_idx is None:
            chosen_idx = 0

        price = None
        if chosen_idx < len(outcome_prices):
            try:
                px = float(outcome_prices[chosen_idx])
                if 0 < px <= 1:
                    # If chosen_idx came from NO alias, convert to YES proxy.
                    if (
                        chosen_idx < len(outcomes)
                        and str(outcomes[chosen_idx]).strip().lower() in no_aliases
                    ):
                        px = round(1.0 - px, 6)
                    price = px
            except Exception:
                price = None

        if price is None:
            last_trade_price = m.get("lastTradePrice")
            try:
                last_trade_price = float(last_trade_price)
            except Exception:
                last_trade_price = None
            if last_trade_price and 0 < last_trade_price <= 1:
                price = last_trade_price

        if price is None or price <= 0 or price > 1:
            continue

        clob_token_id = None
        if chosen_idx < len(clob_ids):
            clob_token_id = str(clob_ids[chosen_idx])
        elif clob_ids:
            clob_token_id = str(clob_ids[0])

        # Calculate End Time from Slug / Event
        # UpDown markets in Polymarket use fixed windows.
        # We can estimate end_time = start_epoch + tf_seconds
        # But even better, Gamma events have an 'endDate' field (ISO format).
        end_time_str = event.get("endDate")
        end_time = 0
        if end_time_str:
            try:
                # ISO to Epoch
                from datetime import datetime

                dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                end_time = int(dt.timestamp())
            except Exception:
                end_time = 0

        markets.append(
            {
                "market_id": str(m.get("id")),
                "condition_id": m.get("conditionId"),
                "clob_token_id": clob_token_id,
                "question": m.get("question", f"{coin.upper()} {timeframe}"),
                "price": float(price),
                "volume": float(m.get("volumeNum") or 0),
                "coin": coin,
                "timeframe": timeframe,
                "selected_outcome": (
                    outcomes[chosen_idx] if chosen_idx < len(outcomes) else "unknown"
                ),
                "end_time": end_time,
                "timestamp": int(time.time()),
            }
        )
    return markets


# ---------------------------
# MAIN ASYNC FETCHER
# ---------------------------
async def fetch_markets_async():
    all_markets = []
    seen = set()
    candidates = generate_candidate_slugs()

    async with aiohttp.ClientSession() as session:
        # We need tf_seconds to pass to parse_market
        tasks = []
        for coin, tf, slug in candidates:
            tasks.append(fetch_event(session, coin, tf, slug))

        results = await asyncio.gather(*tasks)

        for result in results:
            if not result:
                continue
            coin, tf, event = result
            key = f"{coin}-{tf}"
            if key in seen:
                continue

            tf_seconds = TIMEFRAMES.get(tf, 300)
            markets = parse_market(event, coin, tf, tf_seconds)
            if markets:
                now_ts = int(time.time())
                active_future = [m for m in markets if m.get("end_time", 0) > now_ts]
                if active_future:
                    # Prefer the nearest active window (current tradable cycle).
                    selected = min(active_future, key=lambda x: x["end_time"])
                else:
                    # Fallback: highest-volume market from this event payload.
                    selected = max(markets, key=lambda x: x.get("volume", 0.0))
                all_markets.append(selected)
                seen.add(key)

    all_markets.sort(key=lambda x: x["volume"], reverse=True)
    return all_markets


if __name__ == "__main__":
    res = asyncio.run(fetch_markets_async())
    for m in res:
        print(
            f"[{m['coin']}-{m['timeframe']}] {m['price']} | Vol: {m['volume']} | {m['question']}"
        )
