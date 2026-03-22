import sqlite3
import time
import os
import asyncio
import traceback
from dotenv import load_dotenv

from app.logger import get_logger
from app.config import (
    TOP_K, 
    RISK_PROFILES, 
    SELECTED_RISK_PROFILE_NAME, 
    SELECTED_SIZING_PROFILE_NAME,
    FETCH_INTERVAL
)

from data.fetcher import fetch_markets_async
from data.storage import insert_market, get_recent_prices, get_last_price, DB_PATH, init_db, get_recent_oi
from data.websocket_client import PolymarketWS

from features.builder import build_features
from strategy.scorer import compute_score
from strategy.signal import generate_signal
from strategy.paper_trader import execute_virtual_trade, update_paper_trades

load_dotenv()
logger = get_logger()

# --- CONFIG FROM UNIFIED SOURCE ---
RISK_PROFILE_NAME = SELECTED_RISK_PROFILE_NAME
SELECTED_RISK_PROFILE = RISK_PROFILES.get(RISK_PROFILE_NAME)
SIZING_PROFILE_NAME = SELECTED_SIZING_PROFILE_NAME

ACTIVE_MARKETS = {} 
LATEST_PRICES = {}
LATEST_SPREADS = {} # Keep track of current spreads
SEEN_MARKET_IDS = set()
ws_client = PolymarketWS()

# For health tracking
UPDATES_COUNT = 0
LAST_SAVED_PRICE = {}

# Single connection for the whole thread
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

async def process_price_update(token_id, price, spread=None):
    global UPDATES_COUNT
    if not token_id or token_id not in ACTIVE_MARKETS:
        return

    m = ACTIVE_MARKETS[token_id]
    market_id = m["market_id"]
    LATEST_PRICES[market_id] = price
    if spread is not None:
        LATEST_SPREADS[market_id] = spread
    
    UPDATES_COUNT += 1

    # 1. THROTTLE DATABASE WRITES
    last_p = LAST_SAVED_PRICE.get(market_id, 0)
    if abs(last_p - price) >= 0.0001 or UPDATES_COUNT % 50 == 0:
        m["price"] = price
        m["timestamp"] = int(time.time())
        insert_market(conn, m)
        LAST_SAVED_PRICE[market_id] = price
        
        # 2. CALCULATE BITCOIN MACRO TREND
        # We look for any BTC market (preferably 1h) to see overall market direction
        market_context = {"btc_trending_up": True, "btc_trending_down": True}
        try:
            # Query for a stable BTC market (id might vary, so we filter by coin and timeframe)
            # This is a bit of a heuristic, we just want to know if BTC is generally up or down
            cursor = conn.cursor()
            cursor.execute("SELECT price FROM price_history WHERE coin='btc' AND timeframe='1h' ORDER BY timestamp DESC LIMIT 20")
            btc_prices = [row[0] for row in cursor.fetchall()]
            if len(btc_prices) >= 10:
                btc_sma = sum(btc_prices) / len(btc_prices)
                cur_btc = btc_prices[0]
                market_context["btc_trending_up"] = cur_btc > btc_sma
                market_context["btc_trending_down"] = cur_btc < btc_sma
        except:
            pass

        # 3. RUN ANALYSIS
        series = get_recent_prices(conn, market_id, limit=30)
        # Increased to 20 for stability (v21 upgrade)
        if len(series) >= 20: 
            oi_series = get_recent_oi(conn, market_id, limit=10)
            features = build_features(series, m.get("volume", 0), oi_series)
            
            if features:
                # Add current spread to features if available
                cur_spread = LATEST_SPREADS.get(market_id, 0)
                features["current_spread"] = cur_spread

                signal = generate_signal(features, SELECTED_RISK_PROFILE, market_context)
                if signal:
                    # 4. SPREAD FILTER (Safety check)
                    max_allowed_spread = SELECTED_RISK_PROFILE.get("max_spread", 0.03)
                    if cur_spread > max_allowed_spread:
                        # logger.debug(f"⚠️ SPREAD TOO WIDE: {cur_spread} > {max_allowed_spread}")
                        return

                    # 5. EXPIRY CHECK (Protect against "Rug Pulls" near the end)
                    end_time = m.get("end_time", 0)
                    now = int(time.time())
                    remaining = end_time - now
                    
                    if 0 < remaining < 120:
                        # logger.debug(f"⚠️ SKIPPING: {m['coin']} - Too close to expiry ({remaining}s left)")
                        return

                    logger.info(f"✨ WS SIGNAL: [{m['coin']}-{m['timeframe']}] {signal} | P={round(price, 4)} | Spread={round(cur_spread, 4)} | BTC_Up={market_context['btc_trending_up']}")
                    execute_virtual_trade(market_id, m["question"], signal, price, m["coin"], m["timeframe"], SIZING_PROFILE_NAME)

async def on_ws_event(data):
    etype = data.get("event_type")
    if etype == "best_bid_ask":
        bid = float(data.get("best_bid", 0))
        ask = float(data.get("best_ask", 0))
        mid = (bid + ask) / 2
        spread = (ask - bid) if mid > 0 else 0
        await process_price_update(data.get("asset_id"), mid, spread)
    elif etype == "price_change":
        for pc in data.get("price_changes", []):
            bid = float(pc.get("best_bid") or 0)
            ask = float(pc.get("best_ask") or 0)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread = (ask - bid)
                await process_price_update(pc.get("asset_id"), mid, spread)
    elif etype == "book":
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if bids and asks:
            bid = float(bids[0].get("price", 0))
            ask = float(asks[0].get("price", 0))
            mid = (bid + ask) / 2
            spread = (ask - bid)
            await process_price_update(data.get("asset_id"), mid, spread)
    elif etype == "last_trade_price":
        await process_price_update(data.get("asset_id"), float(data.get("price") or 0))

async def sync_loop():
    global UPDATES_COUNT
    while True:
        try:
            markets = await fetch_markets_async()
            new_tokens = []
            for m in markets:
                tid = m.get("clob_token_id")
                if tid and tid not in ACTIVE_MARKETS:
                    ACTIVE_MARKETS[tid] = m
                    new_tokens.append(tid)
            if new_tokens:
                await ws_client.update_subscription(new_tokens)
            update_paper_trades(LATEST_PRICES)
            logger.info(f"📈 STREAM HEALTH: {UPDATES_COUNT} updates last cycle.")
            UPDATES_COUNT = 0
        except Exception as e:
            logger.error(f"Sync Loop Error: {e}")
        await asyncio.sleep(60)

async def run():
    logger.info(f"🚀 Version 18 (Streamer) | Risk: {RISK_PROFILE_NAME} | Size: {SIZING_PROFILE_NAME}")
    init_db()
    initial_markets = await fetch_markets_async()
    initial_tokens = [m["clob_token_id"] for m in initial_markets if m.get("clob_token_id")]
    for m in initial_markets:
        if m.get("clob_token_id"): ACTIVE_MARKETS[m["clob_token_id"]] = m
    asyncio.create_task(sync_loop())
    await ws_client.connect_and_listen(initial_tokens, on_ws_event)

if __name__ == "__main__":
    asyncio.run(run())
