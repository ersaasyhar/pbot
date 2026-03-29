import asyncio
import aiohttp
import time
import json
from app.config import (
    ACTIVE_COINS,
    BOT_CONFIG,
    RISK_PROFILES,
    SELECTED_RISK_PROFILE_NAME,
)
from app.logger import get_logger

BASE_URL = "https://gamma-api.polymarket.com"

BASE_TIMEFRAMES = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}

MAX_RETRIES = 3
logger = get_logger()


def _resolve_discovery_universe():
    profile = RISK_PROFILES.get(SELECTED_RISK_PROFILE_NAME, {})

    # Discovery can be broader than execution.
    # If not set, we fall back to the selected risk profile universe.
    discovery_coins = BOT_CONFIG.get("discovery_allowed_coins", [])
    allowed_coins = discovery_coins or profile.get("trade_allowed_coins", [])
    if allowed_coins:
        coins = [str(c).lower() for c in allowed_coins]
    else:
        coins = [str(c).lower() for c in ACTIVE_COINS]

    discovery_tfs = BOT_CONFIG.get("discovery_allowed_timeframes", [])
    allowed_tfs = discovery_tfs or profile.get("trade_allowed_timeframes", [])
    if allowed_tfs:
        tf_keys = [str(tf) for tf in allowed_tfs if str(tf) in BASE_TIMEFRAMES]
    else:
        tf_keys = list(BASE_TIMEFRAMES.keys())

    timeframes = {k: BASE_TIMEFRAMES[k] for k in tf_keys}
    return coins, timeframes


COINS, TIMEFRAMES = _resolve_discovery_universe()
logger.info(
    f"🌐 Discovery universe | coins={COINS} | timeframes={list(TIMEFRAMES.keys())}"
)


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
            slug_candidates = [f"{coin}-updown-{tf}-{current_epoch}"]
            for offset in range(1, 4):
                try_epoch = current_epoch - (offset * seconds)
                slug_candidates.append(f"{coin}-updown-{tf}-{try_epoch}")
            # Some markets open early; include next epoch as a safety net.
            slug_candidates.append(f"{coin}-updown-{tf}-{current_epoch + seconds}")
            candidates.append((coin, tf, slug_candidates))
    return candidates


# ---------------------------
# ASYNC REQUEST WITH RETRY
# ---------------------------
async def safe_get(session, url, params):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, params=params, timeout=15) as res:
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
                    logger.debug("parse_jsonish: failed to parse JSON string")
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
                        logger.debug("parse_market: invalid NO price")
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
                logger.debug("parse_market: invalid outcome price")
                price = None

        if price is None:
            last_trade_price = m.get("lastTradePrice")
            try:
                last_trade_price = float(last_trade_price)
            except Exception:
                logger.debug("parse_market: invalid lastTradePrice")
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
                logger.debug("parse_market: invalid endDate")
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
    expected_keys = {f"{coin}-{tf}" for coin, tf, _ in candidates}

    async with aiohttp.ClientSession() as session:
        for coin, tf, slugs in candidates:
            key = f"{coin}-{tf}"
            if key in seen:
                continue

            tf_seconds = TIMEFRAMES.get(tf, 300)
            per_key_markets = []
            seen_condition_ids = set()
            for slug in slugs:
                result = await fetch_event(session, coin, tf, slug)
                if not result:
                    continue
                _, _, event = result
                markets = parse_market(event, coin, tf, tf_seconds)
                for market in markets:
                    condition_id = market.get("condition_id")
                    if condition_id and condition_id in seen_condition_ids:
                        continue
                    if condition_id:
                        seen_condition_ids.add(condition_id)
                    per_key_markets.append(market)

            if per_key_markets:
                now_ts = int(time.time())
                active_future = [
                    m for m in per_key_markets if m.get("end_time", 0) > now_ts
                ]
                if active_future:
                    # Prefer the nearest active window (current tradable cycle).
                    selected = min(active_future, key=lambda x: x["end_time"])
                else:
                    # Fallback: highest-volume market from this discovery batch.
                    selected = max(per_key_markets, key=lambda x: x.get("volume", 0.0))
                all_markets.append(selected)
                seen.add(key)

        missing = sorted(expected_keys - seen)
        if missing:
            logger.warning(f"fetch_markets_async: missing markets for {missing}")

    all_markets.sort(key=lambda x: x["volume"], reverse=True)
    return all_markets


if __name__ == "__main__":
    res = asyncio.run(fetch_markets_async())
    for m in res:
        print(
            f"[{m['coin']}-{m['timeframe']}] {m['price']} | Vol: {m['volume']} | {m['question']}"
        )
