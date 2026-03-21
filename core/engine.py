import sqlite3
import time
import os
import asyncio
import traceback
from dotenv import load_dotenv

from app.logger import get_logger
from app.config import *

from data.fetcher import fetch_markets_async
from data.storage import insert_market, get_recent_prices, get_last_price, DB_PATH, init_db, get_recent_oi
from data.clob_client import get_clob_client, get_market_spread
from data.data_client import fetch_open_interest_batch

from features.builder import build_features
from strategy.scorer import compute_score
from strategy.signal import generate_signal
from strategy.paper_trader import execute_virtual_trade, update_paper_trades

load_dotenv()
logger = get_logger()

# Config from .env or defaults
MAX_SPREAD = float(os.getenv("MAX_SPREAD", 0.03))

async def run():
    logger.info("Starting Polymarket Engine (Async v2 + CLOB + OI Guard)...")
    
    # Ensure DB is initialized
    init_db()

    # Initialize CLOB client
    clob_client = get_clob_client()

    while True:
        conn = sqlite3.connect(DB_PATH)
        
        try:
            logger.info("=== FETCHING MARKETS ===")
            markets = await fetch_markets_async()
            logger.info(f"Markets received: {len(markets)}")

            if not markets:
                conn.close()
                await asyncio.sleep(FETCH_INTERVAL)
                continue

            # --- NEW: BATCH FETCH OPEN INTEREST ---
            condition_ids = [m.get("condition_id") for m in markets if m.get("condition_id")]
            oi_data = await fetch_open_interest_batch(condition_ids)
            
            signals = []
            processed = 0
            skipped_duplicates = 0
            blocked_by_spread = 0
            
            # For paper trader updates
            latest_prices = {}

            with conn:
                for m in markets:
                    try:
                        market_id = m.get("market_id")
                        cond_id = m.get("condition_id")
                        clob_token_id = m.get("clob_token_id")
                        question = m.get("question")
                        price = float(m.get("price", 0))
                        volume = float(m.get("volume", 0))
                        coin = m.get("coin", "unknown")
                        tf = m.get("timeframe", "unknown")

                        if any(x is None for x in [market_id, question, price, volume, coin, tf]):
                            continue
                            
                        # Add OI to the market dict for storage
                        m["open_interest"] = oi_data.get(cond_id, 0.0)
                        
                        latest_prices[market_id] = price

                        # ✅ volume guard
                        if volume < MIN_VOLUME:
                            continue

                        # ✅ DUPLICATE FILTER
                        last_data = get_last_price(conn, market_id)
                        if last_data:
                            if abs(last_data["price"] - price) < 1e-6 and abs(last_data["volume"] - volume) < 1.0:
                                skipped_duplicates += 1
                                continue

                        # ✅ STORE
                        insert_market(conn, m)

                        # ✅ TIME SERIES
                        series = get_recent_prices(conn, market_id, limit=30)
                        if len(series) < 10:
                            continue
                            
                        # Fetch recent OI for trend calculation
                        oi_series = get_recent_oi(conn, market_id, limit=10)

                        # ✅ FEATURES + SIGNAL
                        features = build_features(series, volume, oi_series)
                        if not features:
                            continue

                        score = compute_score(features)
                        signal = generate_signal(features)

                        # ✅ CLOB SPREAD GUARD (Only check if we actually have a signal)
                        if signal and clob_token_id:
                            spread_info = get_market_spread(clob_client, clob_token_id)
                            if spread_info:
                                spread = spread_info["spread"]
                                if spread > MAX_SPREAD:
                                    blocked_by_spread += 1
                                    continue
                            else:
                                continue

                        if signal:
                            signals.append((score, signal, question, coin, tf))
                            processed += 1
                            
                            # ✅ EXECUTE PAPER TRADE
                            execute_virtual_trade(market_id, question, signal, price, coin, tf)

                    except Exception as e:
                        logger.error(f"Market processing error on {m.get('market_id')}: {e}")
                        continue

            # ✅ UPDATE ACTIVE PAPER TRADES (Exit Logic)
            update_paper_trades(latest_prices)

            # ✅ SORT SIGNALS
            signals.sort(key=lambda x: x[0], reverse=True)
            for s in signals[:TOP_K]:
                logger.info(f"[{s[3]}-{s[4]}] {s[1]} | score={round(s[0], 2)} | {s[2][:80]}")

            logger.info(f"=== CYCLE SUMMARY: Processed {processed}, Skipped {skipped_duplicates}, Blocked(Spread) {blocked_by_spread} ===")

        except Exception as e:
            logger.error(f"Engine error: {e}")
        
        finally:
            conn.close()

        await asyncio.sleep(FETCH_INTERVAL)
