import sqlite3
import math
from features.builder import build_features
from strategy.signal import generate_trend_signal, generate_mean_reversion_signal
from backtest.simulator import Trade
from data.storage import DB_PATH
from app.config import RISK_PROFILES, SELECTED_RISK_PROFILE_NAME

# Use the same unified profile as the live bot
PROFILE_NAME = SELECTED_RISK_PROFILE_NAME
TP = 0.05
SL = -0.05


def detect_regime(features, timeframe):
    rel_vol = features.get("rel_vol", 1.0)
    momentum_pct = abs(features.get("momentum_pct", 0.0))
    z_abs = abs(features.get("z_score", 0.0))

    if rel_vol >= 1.35:
        return "volatile"
    if timeframe in ["1h", "4h"]:
        return "trend" if z_abs >= 0.8 or momentum_pct >= 0.02 else "range"
    return "trend" if z_abs >= 1.5 or momentum_pct >= 0.03 else "range"


def backtest():
    print(f"📈 Running Backtest using {PROFILE_NAME} profile (Unified Config)...")
    profile = RISK_PROFILES.get(PROFILE_NAME, RISK_PROFILES.get("BALANCED"))

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='market_prices'"
    )
    if not cur.fetchone():
        print("❌ No data found in database.")
        return

    cur.execute("""
        SELECT market_id, question, coin, timeframe, price, timestamp
        FROM market_prices
        ORDER BY timestamp
    """)

    data = cur.fetchall()
    if not data:
        print("❌ Database is empty.")
        return

    history = {}
    btc_history = {}
    trades = []
    active_trades = {}
    pnl_total = 0

    for row in data:
        market_id, question, coin, timeframe, price, ts = row
        if market_id not in history:
            history[market_id] = []
        history[market_id].append(price)
        series = history[market_id][-30:]

        # Build BTC context by timeframe as a macro filter proxy.
        if coin == "btc":
            if timeframe not in btc_history:
                btc_history[timeframe] = []
            btc_history[timeframe].append(price)

        features = build_features(series, volume=1000, oi_series=None)
        if not features:
            continue

        # Backtest DB does not store order-book depth/pressure snapshots.
        # Use z-score direction as a lightweight pressure proxy.
        features["pressure"] = math.tanh(features.get("z_score", 0.0) / 2.0)

        # ENTRY
        if market_id not in active_trades:
            btc_series = btc_history.get(timeframe, [])[-20:]
            btc_up = True
            btc_down = True
            if len(btc_series) >= 10:
                btc_sma = sum(btc_series) / len(btc_series)
                btc_now = btc_series[-1]
                btc_up = btc_now > btc_sma
                btc_down = btc_now < btc_sma

            market_context = {
                "btc_trending_up": btc_up,
                "btc_trending_down": btc_down,
                "timeframe": timeframe,
            }
            regime = detect_regime(features, timeframe)
            if regime == "volatile":
                signal, confidence = None, 0.0
            elif timeframe in ["1h", "4h"] or regime == "trend":
                signal, confidence = generate_trend_signal(
                    features, profile, market_context
                )
            else:
                signal, confidence = generate_mean_reversion_signal(
                    features, profile, market_context
                )

            if signal:
                active_trades[market_id] = Trade(signal, price)

        # EXIT
        if market_id in active_trades:
            trade = active_trades[market_id]
            pnl = trade.pnl(price)
            if pnl >= TP or pnl <= SL:
                pnl_total += pnl
                trades.append(pnl)
                del active_trades[market_id]

    print("\n" + "=" * 40)
    print(f"BACKTEST RESULTS ({PROFILE_NAME})")
    print("=" * 40)
    print(f"Closed PnL: {round(pnl_total, 4)}")
    print(f"Closed Trades: {len(trades)}")

    if trades:
        winrate = sum(1 for t in trades if t > 0) / len(trades)
        print(f"Win Rate (Closed): {round(winrate * 100, 2)}%")


if __name__ == "__main__":
    backtest()
