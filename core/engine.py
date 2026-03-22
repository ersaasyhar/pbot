import sqlite3
import time
import asyncio
import math
from dotenv import load_dotenv

from app.logger import get_logger
from app.config import (
    RISK_PROFILES,
    SELECTED_RISK_PROFILE_NAME,
    SELECTED_SIZING_PROFILE_NAME,
)

from data.fetcher import fetch_markets_async
from data.storage import (
    insert_market,
    get_recent_prices,
    DB_PATH,
    init_db,
    get_recent_oi,
)
from data.websocket_client import PolymarketWS

from features.builder import build_features
from strategy.signal import generate_trend_signal, generate_mean_reversion_signal
from strategy.paper_trader import execute_virtual_trade, update_paper_trades

load_dotenv()
logger = get_logger()

# --- CONFIG FROM UNIFIED SOURCE ---
RISK_PROFILE_NAME = SELECTED_RISK_PROFILE_NAME
SELECTED_RISK_PROFILE = RISK_PROFILES.get(RISK_PROFILE_NAME)
SIZING_PROFILE_NAME = SELECTED_SIZING_PROFILE_NAME

ACTIVE_MARKETS = {}
LATEST_PRICES = {}
LATEST_SPREADS = {}
LATEST_PRESSURE = {}  # Track Order Book Pressure
LATEST_DEPTH = {}
LATEST_ANALYSIS = {}
SIGNAL_STATE = {}
ENTRY_CANDIDATES = {}
SEEN_MARKET_IDS = set()
ws_client = PolymarketWS()

# For health tracking
UPDATES_COUNT = 0
LAST_SAVED_PRICE = {}

# Single connection for the whole thread (initialized in run)
conn = None


def detect_regime(features, timeframe):
    rel_vol = features.get("rel_vol", 1.0)
    momentum_pct = abs(features.get("momentum_pct", 0.0))
    z_abs = abs(features.get("z_score", 0.0))

    if rel_vol >= 1.35:
        return "volatile"

    if timeframe in ["1h", "4h"]:
        return "trend" if z_abs >= 0.8 or momentum_pct >= 0.02 else "range"

    return "trend" if z_abs >= 1.5 or momentum_pct >= 0.03 else "range"


def queue_trade_candidate(candidate):
    market_id = candidate["market_id"]
    previous = ENTRY_CANDIDATES.get(market_id)
    if (not previous) or candidate["decayed_ev"] > previous["decayed_ev"]:
        ENTRY_CANDIDATES[market_id] = candidate


def execute_top_candidates():
    if not ENTRY_CANDIDATES:
        return

    now = int(time.time())
    max_entries = int(SELECTED_RISK_PROFILE.get("max_entries_per_cycle", 3))
    max_age_sec = int(SELECTED_RISK_PROFILE.get("max_signal_age_sec", 60))

    ranked = sorted(
        ENTRY_CANDIDATES.values(), key=lambda x: x["decayed_ev"], reverse=True
    )
    selected = 0
    for c in ranked:
        if selected >= max_entries:
            break
        if now - c["queued_at"] > max_age_sec:
            continue

        execute_virtual_trade(
            c["market_id"],
            c["question"],
            c["side"],
            c["price"],
            c["coin"],
            c["timeframe"],
            SIZING_PROFILE_NAME,
            c["confidence"],
            effective_ev=c["decayed_ev"],
            regime=c["regime"],
            signal_age_sec=c["signal_age_sec"],
        )
        selected += 1

    ENTRY_CANDIDATES.clear()


async def process_price_update(token_id, price, spread=None, pressure=0.0, depth=None):
    global UPDATES_COUNT
    if conn is None:
        return
    if not token_id or token_id not in ACTIVE_MARKETS:
        return

    m = ACTIVE_MARKETS[token_id]
    market_id = m["market_id"]
    LATEST_PRICES[market_id] = price
    if spread is not None:
        LATEST_SPREADS[market_id] = spread

    LATEST_PRESSURE[market_id] = pressure
    if depth is not None:
        LATEST_DEPTH[market_id] = depth

    UPDATES_COUNT += 1

    # 1. THROTTLE DATABASE WRITES
    last_p = LAST_SAVED_PRICE.get(market_id, 0)
    if abs(last_p - price) >= 0.0001 or UPDATES_COUNT % 50 == 0:
        m["price"] = price
        m["timestamp"] = int(time.time())
        insert_market(conn, m)
        LAST_SAVED_PRICE[market_id] = price

        # 2. CALCULATE BITCOIN MACRO TREND
        market_context = {
            "btc_trending_up": True,
            "btc_trending_down": True,
            "timeframe": m.get("timeframe", "5m"),
        }
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT price FROM market_prices WHERE coin='btc' AND timeframe='1h' ORDER BY timestamp DESC LIMIT 20"
            )
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
        if len(series) >= 20:
            oi_series = get_recent_oi(conn, market_id, limit=10)
            features = build_features(series, m.get("volume", 0), oi_series)

            if features:
                # --- v30: DEBUG LOGGING ---
                # Log all features and context for every analysis cycle
                ev = (features.get("confidence", 0.5) * 0.10) - (
                    (1.0 - features.get("confidence", 0.5)) * 0.05
                )
                log_msg = (
                    f"ANALYSIS [{m['coin']}-{m['timeframe']}] | "
                    f"P: {features['price']:.3f}, "
                    f"Z: {features['z_score']:.2f}, "
                    f"RSI: {features['rsi']:.1f}, "
                    f"RelVol: {features['rel_vol']:.2f}, "
                    f"Pressure: {features.get('pressure', 0):.2f}, "
                    f"EV: {ev:+.2f}"
                )
                logger.debug(log_msg)

                cur_spread = LATEST_SPREADS.get(market_id, 0)
                cur_pressure = LATEST_PRESSURE.get(market_id, 0.0)
                cur_depth = LATEST_DEPTH.get(market_id, 0.0)
                features["current_spread"] = cur_spread
                features["pressure"] = cur_pressure
                features["depth_top5"] = cur_depth

                regime = detect_regime(features, m.get("timeframe", "5m"))
                market_context["regime"] = regime

                # v31: STRATEGY ROUTER
                timeframe = m.get("timeframe", "5m")

                if regime == "volatile":
                    signal, confidence = None, 0.0
                    strategy_name = "SKIP_VOLATILE"
                elif timeframe in ["1h", "4h"] or regime == "trend":
                    signal, confidence = generate_trend_signal(
                        features, SELECTED_RISK_PROFILE, market_context
                    )
                    strategy_name = "TREND"
                else:
                    signal, confidence = generate_mean_reversion_signal(
                        features, SELECTED_RISK_PROFILE, market_context
                    )
                    strategy_name = "REVERSION"

                # Continuous state used for lifecycle exits.
                # Heuristic EV proxy when no entry signal is active.
                z_strength = min(abs(features.get("z_score", 0.0)) / 3.0, 1.0)
                base_confidence = 0.5 + (z_strength * 0.2)
                base_ev = (base_confidence * 0.10) - ((1.0 - base_confidence) * 0.05)
                LATEST_ANALYSIS[market_id] = {
                    "timestamp": int(time.time()),
                    "pressure": cur_pressure,
                    "depth_top5": cur_depth,
                    "z_score": features.get("z_score", 0.0),
                    "momentum": features.get("momentum", 0.0),
                    "effective_ev": base_ev,
                    "regime": regime,
                }

                if signal:
                    # 4. EXPECTED VALUE (EV) CHECK
                    tp_reward = 0.10
                    sl_risk = 0.05
                    raw_ev = (confidence * tp_reward) - ((1.0 - confidence) * sl_risk)

                    # 5. SPREAD FILTER
                    max_allowed_spread = SELECTED_RISK_PROFILE.get("max_spread", 0.03)
                    if cur_spread > max_allowed_spread:
                        return

                    # 6. LIQUIDITY FILTER
                    min_depth = SELECTED_RISK_PROFILE.get("min_depth_top5", 200.0)
                    if cur_depth > 0 and cur_depth < min_depth:
                        return

                    # 7. EV FRICTION PENALTY (spread + slippage)
                    spread_cost = (cur_spread / max(price, 0.20)) * 0.5
                    slippage_cost = 0.005
                    effective_ev = raw_ev - spread_cost - slippage_cost
                    min_effective_ev = SELECTED_RISK_PROFILE.get(
                        "min_effective_ev", 0.03
                    )
                    if effective_ev < min_effective_ev:
                        return

                    # 8. SIGNAL AGE DECAY
                    now = int(time.time())
                    state = SIGNAL_STATE.get(market_id)
                    if state and state.get("side") == signal:
                        first_seen = state.get("first_seen", now)
                    else:
                        first_seen = now
                        SIGNAL_STATE[market_id] = {
                            "side": signal,
                            "first_seen": first_seen,
                        }

                    signal_age_sec = max(0, now - first_seen)
                    max_signal_age_sec = int(
                        SELECTED_RISK_PROFILE.get("max_signal_age_sec", 60)
                    )
                    if signal_age_sec > max_signal_age_sec:
                        return

                    decay_lambda = float(
                        SELECTED_RISK_PROFILE.get("signal_decay_lambda", 0.02)
                    )
                    decay = math.exp(-decay_lambda * signal_age_sec)
                    decayed_ev = effective_ev * decay
                    if decayed_ev < min_effective_ev:
                        return

                    # 9. EXPIRY CHECK
                    end_time = m.get("end_time", 0)
                    remaining = end_time - now
                    if 0 < remaining < 120:
                        return

                    LATEST_ANALYSIS[market_id]["effective_ev"] = decayed_ev

                    log_msg = (
                        f"✨ {strategy_name} SIGNAL: [{m['coin']}-{m['timeframe']}] {signal} "
                        f"({int(confidence * 100)}%) | EV(raw/eff/decay): +{round(raw_ev * 100, 1)}%/+{round(effective_ev * 100, 1)}%/+{round(decayed_ev * 100, 1)}% "
                        f"| Age={signal_age_sec}s | P={round(price, 4)} | Regime={regime}"
                    )
                    logger.info(log_msg)
                    queue_trade_candidate(
                        {
                            "market_id": market_id,
                            "question": m["question"],
                            "side": signal,
                            "price": price,
                            "coin": m["coin"],
                            "timeframe": m["timeframe"],
                            "confidence": confidence,
                            "regime": regime,
                            "signal_age_sec": signal_age_sec,
                            "decayed_ev": decayed_ev,
                            "queued_at": now,
                        }
                    )
                else:
                    SIGNAL_STATE.pop(market_id, None)


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
                spread = ask - bid
                await process_price_update(pc.get("asset_id"), mid, spread)
    elif etype == "book":
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if bids and asks:
            # 1. TOP OF BOOK (for Midpoint/Spread)
            bid_p = float(bids[0].get("price", 0))
            ask_p = float(asks[0].get("price", 0))
            mid = (bid_p + ask_p) / 2
            spread = ask_p - bid_p

            # 2. DEEP ORDER BOOK IMBALANCE (OBI) - Top 5 levels
            # We look at 'depth' to see hidden walls
            top_bids = bids[:5]
            top_asks = asks[:5]

            total_bid_vol = sum([float(b.get("size", 0)) for b in top_bids])
            total_ask_vol = sum([float(a.get("size", 0)) for a in top_asks])

            # Weighted Pressure: (Bid Vol - Ask Vol) / Total Vol
            total_v = total_bid_vol + total_ask_vol
            deep_pressure = (
                (total_bid_vol - total_ask_vol) / total_v if total_v > 0 else 0
            )

            await process_price_update(
                data.get("asset_id"), mid, spread, deep_pressure, total_v
            )
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
            execute_top_candidates()
            update_paper_trades(LATEST_PRICES, LATEST_ANALYSIS)
            logger.info(f"📈 STREAM HEALTH: {UPDATES_COUNT} updates last cycle.")
            UPDATES_COUNT = 0
        except Exception as e:
            logger.error(f"Sync Loop Error: {e}")
        await asyncio.sleep(60)


async def run():
    global conn
    logger.info(
        f"🚀 v34 (Decay + TopN + Metrics + fast calibration) | Risk: {RISK_PROFILE_NAME} | Size: {SIZING_PROFILE_NAME}"
    )
    init_db()
    conn = sqlite3.connect(
        DB_PATH, check_same_thread=False, timeout=30, isolation_level=None
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")

    ACTIVE_MARKETS.clear()
    LATEST_PRICES.clear()
    LATEST_SPREADS.clear()
    LATEST_PRESSURE.clear()
    LATEST_DEPTH.clear()
    LATEST_ANALYSIS.clear()
    SIGNAL_STATE.clear()
    ENTRY_CANDIDATES.clear()

    initial_markets = await fetch_markets_async()
    initial_tokens = [
        m["clob_token_id"] for m in initial_markets if m.get("clob_token_id")
    ]
    for m in initial_markets:
        if m.get("clob_token_id"):
            ACTIVE_MARKETS[m["clob_token_id"]] = m
    logger.info(f"Loaded {len(initial_tokens)} markets for initial WS subscription.")
    asyncio.create_task(sync_loop())
    await ws_client.connect_and_listen(initial_tokens, on_ws_event)


if __name__ == "__main__":
    asyncio.run(run())
