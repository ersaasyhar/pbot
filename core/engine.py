import sqlite3
import time
import os
import asyncio
import traceback
from dotenv import load_dotenv

from app.logger import get_logger
from app.config import *
from app.profiles import RISK_PROFILES

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

# --- LOAD PROFILES FROM ENV ---
RISK_PROFILE_NAME = os.getenv("RISK_PROFILE", "BALANCED").upper()
SIZING_PROFILE_NAME = os.getenv("SIZING_PROFILE", "FIXED").upper()

# Get actual profile dicts
SELECTED_RISK_PROFILE = RISK_PROFILES.get(RISK_PROFILE_NAME, RISK_PROFILES["BALANCED"])
MAX_SPREAD = SELECTED_RISK_PROFILE["max_spread"]
MIN_VOL = SELECTED_RISK_PROFILE["min_volume"]

async def run():
    logger.info(f"Starting Polymarket Engine...")
    logger.info(f"Active Profiles: Risk={RISK_PROFILE_NAME}, Sizing={SIZING_PROFILE_NAME}")
    
    init_db()
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

            # Batch fetch OI
            condition_ids = [m.get("condition_id") for m in markets if m.get("condition_id")]
            oi_data = await fetch_open_interest_batch(condition_ids)
            
            signals = []
            processed = 0
            skipped_duplicates = 0
            blocked_by_spread = 0
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
                            
                        latest_prices[market_id] = price
                        m["open_interest"] = oi_data.get(cond_id, 0.0)

                        # ✅ volume guard (using profile setting)
                        if volume < MIN_VOL:
                            continue

                        # ✅ DUPLICATE FILTER
                        last_data = get_last_price(conn, market_id)
                        if last_data:
                            if abs(last_data["price"] - price) < 1e-6 and abs(last_data["volume"] - volume) < 1.0:
                                skipped_duplicates += 1
                                continue

                        insert_market(conn, m)

                        # ✅ TIME SERIES
                        series = get_recent_prices(conn, market_id, limit=30)
                        if len(series) < 10:
                            continue
                        oi_series = get_recent_oi(conn, market_id, limit=10)

                        # ✅ FEATURES + SIGNAL (passing profile)
                        features = build_features(series, volume, oi_series)
                        if not features:
                            continue

                        score = compute_score(features)
                        signal = generate_signal(features, SELECTED_RISK_PROFILE)

                        # ✅ CLOB SPREAD GUARD
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
                            
                            # ✅ EXECUTE PAPER TRADE (passing sizing profile)
                            execute_virtual_trade(market_id, question, signal, price, coin, tf, SIZING_PROFILE_NAME)

                    except Exception as e:
                        logger.error(f"Market processing error on {m.get('market_id')}: {e}")
                        continue

            update_paper_trades(latest_prices)

            # SORT SIGNALS
            signals.sort(key=lambda x: x[0], reverse=True)
            for s in signals[:TOP_K]:
                logger.info(f"[{s[3]}-{s[4]}] {s[1]} | score={round(s[0], 2)} | {s[2][:80]}")

            logger.info(f"=== CYCLE SUMMARY: Processed {processed}, Skipped {skipped_duplicates}, Blocked(Spread) {blocked_by_spread} ===")

        except Exception as e:
            logger.error(f"Engine error: {e}")
        
        finally:
            conn.close()

        await asyncio.sleep(FETCH_INTERVAL)
