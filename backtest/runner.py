import sqlite3
import os
from features.builder import build_features
from strategy.signal import generate_signal
from backtest.simulator import Trade
from data.storage import DB_PATH
from app.config import RISK_PROFILES, SELECTED_RISK_PROFILE_NAME

# Use the same unified profile as the live bot
PROFILE_NAME = SELECTED_RISK_PROFILE_NAME
TP = 0.05
SL = -0.05

def backtest():
    print(f"📈 Running Backtest using {PROFILE_NAME} profile (Unified Config)...")
    profile = RISK_PROFILES.get(PROFILE_NAME, RISK_PROFILES.get("BALANCED"))

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_prices'")
    if not cur.fetchone():
        print("❌ No data found in database.")
        return

    cur.execute("""
        SELECT market_id, question, price, timestamp
        FROM market_prices
        ORDER BY timestamp
    """)

    data = cur.fetchall()
    if not data:
        print("❌ Database is empty.")
        return

    history = {}
    trades = []
    active_trades = {}
    pnl_total = 0

    for row in data:
        market_id, question, price, ts = row
        if market_id not in history: history[market_id] = []
        history[market_id].append(price)
        series = history[market_id][-30:]

        features = build_features(series, volume=1000, oi_series=None)
        if not features: continue

        # ENTRY
        if market_id not in active_trades:
            signal = generate_signal(features, profile)
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

    print("\n" + "="*40)
    print(f"BACKTEST RESULTS ({PROFILE_NAME})")
    print("="*40)
    print(f"Closed PnL: {round(pnl_total, 4)}")
    print(f"Closed Trades: {len(trades)}")
    
    if trades:
        winrate = sum(1 for t in trades if t > 0) / len(trades)
        print(f"Win Rate (Closed): {round(winrate * 100, 2)}%")

if __name__ == "__main__":
    backtest()
