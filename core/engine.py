import sqlite3
import time
import os
import asyncio

from app.logger import get_logger
from app.config import *

from data.fetcher import fetch_markets_async
from data.storage import insert_market, get_recent_prices, get_last_price, DB_PATH

from features.builder import build_features
from strategy.scorer import compute_score
from strategy.signal import generate_signal

logger = get_logger()


async def run():
    logger.info("Starting Polymarket Engine (Async v2)...")

    while True:
        # Connect inside the loop to ensure we don't hold a stale/locked connection
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        try:
            logger.info("=== FETCHING MARKETS ===")

            # Using the new async fetcher
            markets = await fetch_markets_async()
            logger.info(f"Markets received: {len(markets)}")

            if not markets:
                logger.warning("No markets fetched — check filters/API")
                conn.close()
                await asyncio.sleep(FETCH_INTERVAL)
                continue

            signals = []
            processed = 0
            skipped_duplicates = 0

            # ✅ Use 'with conn:' to wrap the entire loop in a single transaction
            with conn:
                for m in markets:
                    try:
                        market_id = m["market_id"]
                        question = m["question"]
                        price = m["price"]
                        volume = m["volume"]

                        # ✅ volume guard
                        if volume < MIN_VOLUME:
                            continue

                        # ✅ DUPLICATE FILTER
                        last = get_last_price(conn, market_id)
                        if last and abs(last["price"] - price) < 1e-6:
                            skipped_duplicates += 1
                            continue

                        # ✅ STORE
                        insert_market(conn, m)

                        # ✅ TIME SERIES
                        series = get_recent_prices(conn, market_id)
                        if len(series) < 10:
                            continue

                        # ✅ FEATURES + SIGNAL
                        features = build_features(series, volume)
                        if not features:
                            continue

                        score = compute_score(features)
                        signal = generate_signal(features)

                        if signal:
                            signals.append((score, signal, question, m["coin"], m["timeframe"]))
                            processed += 1

                    except Exception as e:
                        logger.error(f"Market processing error: {e}")
                        continue

            # ✅ SORT SIGNALS
            signals.sort(key=lambda x: x[0], reverse=True)
            for s in signals[:TOP_K]:
                logger.info(f"[{s[3]}-{s[4]}] {s[1]} | score={round(s[0], 2)} | {s[2][:80]}")

            logger.info(f"=== CYCLE SUMMARY: Processed {processed}, Skipped {skipped_duplicates} ===")

        except Exception as e:
            logger.error(f"Engine error: {e}")
        
        finally:
            conn.close()

        await asyncio.sleep(FETCH_INTERVAL)
