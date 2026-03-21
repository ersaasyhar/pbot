import sqlite3
import json
import os
from datetime import datetime

# Path to virtual state
STATE_PATH = "db/paper_portfolio.json"

def load_portfolio():
    if not os.path.exists(STATE_PATH):
        return {"balance": 1000.0, "active_trades": {}, "history": []}
    with open(STATE_PATH, 'r') as f:
        return json.load(f)

def save_portfolio(data):
    with open(STATE_PATH, 'w') as f:
        json.dump(data, f, indent=4)

def execute_virtual_trade(market_id, question, side, price, coin, timeframe):
    """
    Simulates a $100 entry per signal
    """
    portfolio = load_portfolio()
    
    # Check if we already have a trade open for this market
    if market_id in portfolio["active_trades"]:
        return
        
    entry_cost = 100.0 # $100 virtual bet
    num_shares = entry_cost / price
    
    portfolio["active_trades"][market_id] = {
        "question": question,
        "side": side,
        "entry_price": price,
        "shares": num_shares,
        "coin": coin,
        "timeframe": timeframe,
        "entry_at": str(datetime.now())
    }
    
    print(f"📄 PAPER TRADE: {side} {question[:40]} @ {price}")
    save_portfolio(portfolio)

def update_paper_trades(current_prices):
    """
    Checks TP/SL for all active virtual trades
    current_prices: dict {market_id: current_price}
    """
    portfolio = load_portfolio()
    TP = 0.05
    SL = -0.05
    
    closed_any = False
    to_delete = []
    
    for m_id, trade in portfolio["active_trades"].items():
        if m_id not in current_prices:
            continue
            
        cur_price = current_prices[m_id]
        entry = trade["entry_price"]
        
        # Calculate PnL per share
        if trade["side"] == "BUY YES":
            pnl_per_share = cur_price - entry
        else: # BUY NO
            pnl_per_share = entry - cur_price
            
        if pnl_per_share >= TP or pnl_per_share <= SL:
            # Close trade
            total_pnl = pnl_per_share * trade["shares"]
            trade["exit_price"] = cur_price
            trade["exit_at"] = str(datetime.now())
            trade["pnl"] = total_pnl
            
            portfolio["history"].append(trade)
            portfolio["balance"] += total_pnl
            to_delete.append(m_id)
            closed_any = True
            
            status = "💰 PROFIT" if total_pnl > 0 else "🛑 STOP"
            print(f"📄 PAPER EXIT: {status} | PnL=${round(total_pnl, 2)} | {trade['question'][:40]}")

    for m_id in to_delete:
        del portfolio["active_trades"][m_id]
        
    if closed_any:
        save_portfolio(portfolio)
