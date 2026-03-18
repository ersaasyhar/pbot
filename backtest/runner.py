import sqlite3
from features.builder import build_features
from strategy.signal import generate_signal
from backtest.simulator import Trade
from data.storage import DB_PATH

TP = 0.03
SL = -0.04

def backtest():

    # Using the live DB_PATH from storage.py (which is now v4)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ✅ FIXED: also select market_id
    cur.execute("""
        SELECT market_id, question, price, timestamp
        FROM market_prices
        ORDER BY timestamp
    """)

    data = cur.fetchall()

    history = {}
    trades = []
    active_trades = {} # ✅ Track active trade PER market
    pnl_total = 0

    for row in data:
        market_id, question, price, ts = row

        if market_id not in history:
            history[market_id] = []

        history[market_id].append(price)

        series = history[market_id][-30:]

        features = build_features(series, volume=1000)

        if not features:
            continue

        # ENTRY logic per market
        if market_id not in active_trades:
            signal = generate_signal(features)

            if signal:
                active_trades[market_id] = Trade(signal, price)
                print(f"🚀 ENTRY [{signal}] | {question[:40]} | price={price}")


        # EXIT logic per market
        if market_id in active_trades:
            trade = active_trades[market_id]
            pnl = trade.pnl(price)

            if pnl >= TP or pnl <= SL:
                pnl_total += pnl
                trades.append(pnl)
                del active_trades[market_id]
                status = "💰 PROFIT" if pnl > 0 else "🛑 STOP"
                print(f"{status} | PnL={round(pnl, 4)} | {question[:40]}")

    print("\n" + "="*40)
    print("BACKTEST RESULTS")
    print("="*40)
    print(f"Closed PnL: {round(pnl_total, 4)}")
    print(f"Closed Trades: {len(trades)}")
    
    if active_trades:
        print("\n--- OPEN TRADES ---")
        unrealized_pnl = 0
        for m_id, trade in active_trades.items():
            # Get the very last price we have for this market
            current_p = history[m_id][-1]
            pnl = trade.pnl(current_p)
            unrealized_pnl += pnl
            print(f"RUNNING | PnL={round(pnl, 4)} | Entry={trade.entry} | Cur={current_p}")
        print(f"Total Unrealized PnL: {round(unrealized_pnl, 4)}")
        print(f"COMBINED PNL: {round(pnl_total + unrealized_pnl, 4)}")

    if trades:
        winrate = sum(1 for t in trades if t > 0) / len(trades)
        avg_pnl = sum(trades) / len(trades)
        print(f"\nWin Rate (Closed): {round(winrate * 100, 2)}%")
    else:
        print("\nWin Rate (Closed): 0%")

if __name__ == "__main__":
    backtest()
