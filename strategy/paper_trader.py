import sqlite3
import json
import os
from datetime import datetime
from app.profiles import SIZING_PROFILES

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

def calculate_stake(portfolio, sizing_profile_name):
    """
    Determines how much to bet based on the sizing profile.
    """
    profile = SIZING_PROFILES.get(sizing_profile_name, SIZING_PROFILES["FIXED"])
    
    if profile["type"] == "fixed":
        return profile["value"]
    else:
        # Percentage of current balance
        return portfolio["balance"] * profile["value"]

def execute_virtual_trade(market_id, question, side, price, coin, timeframe, sizing_profile="FIXED"):
    """
    Simulates an entry based on sizing profile
    """
    portfolio = load_portfolio()
    
    if market_id in portfolio["active_trades"]:
        return
        
    entry_cost = calculate_stake(portfolio, sizing_profile)
    
    # Ensure we have enough balance
    if entry_cost > portfolio["balance"]:
        # print(f"⚠️ Insufficient paper balance for {question[:20]}")
        return

    num_shares = entry_cost / price
    
    portfolio["active_trades"][market_id] = {
        "question": question,
        "side": side,
        "entry_price": price,
        "entry_cost": entry_cost,
        "shares": num_shares,
        "coin": coin,
        "timeframe": timeframe,
        "entry_at": str(datetime.now())
    }
    
    # We "lock" the entry cost from the balance
    portfolio["balance"] -= entry_cost
    
    print(f"📄 PAPER TRADE: {side} {question[:40]} | Stake: ${round(entry_cost, 2)} @ {price}")
    save_portfolio(portfolio)

def update_paper_trades(current_prices):
    """
    Checks TP/SL for all active virtual trades
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
            # Total payout = current value of shares
            # If we bought YES at 0.50 and it's now 0.55, payout = shares * 0.55
            # Simplified: total_pnl = pnl_per_share * shares
            total_pnl = pnl_per_share * trade["shares"]
            payout = trade["entry_cost"] + total_pnl
            
            trade["exit_price"] = cur_price
            trade["exit_at"] = str(datetime.now())
            trade["pnl"] = total_pnl
            
            portfolio["history"].append(trade)
            portfolio["balance"] += payout # Return stake + profit (or minus loss)
            to_delete.append(m_id)
            closed_any = True
            
            status = "💰 PROFIT" if total_pnl > 0 else "🛑 STOP"
            print(f"📄 PAPER EXIT: {status} | PnL=${round(total_pnl, 2)} | {trade['question'][:40]}")

    for m_id in to_delete:
        del portfolio["active_trades"][m_id]
        
    if closed_any:
        save_portfolio(portfolio)
