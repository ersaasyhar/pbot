import sqlite3
import json
import os
from datetime import datetime
from app.config import SIZING_PROFILES

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
    profile = SIZING_PROFILES.get(sizing_profile_name, SIZING_PROFILES.get("FIXED"))
    if profile["type"] == "fixed":
        return float(profile["value"])
    else:
        return round(portfolio["balance"] * profile["value"], 2)

def execute_virtual_trade(market_id, question, side, price, coin, timeframe, sizing_profile="FIXED"):
    """
    v21: SYMMETRIC PRECISION
    - Correctly handles BUY NO price (1.0 - price)
    - Enforces strict safety zone (0.20 - 0.80)
    """
    # Strict Safety Zone Check (YES price must be between 0.20 and 0.80)
    if price < 0.20 or price > 0.80:
        return

    portfolio = load_portfolio()
    if market_id in portfolio["active_trades"]:
        return
        
    entry_cost = calculate_stake(portfolio, sizing_profile)
    # MINIMUM STAKE $1.00
    if entry_cost < 1.0 or entry_cost > portfolio["balance"]:
        return

    # Determine actual price of the token we are buying
    # If side is BUY NO, we buy the NO token which costs (1.0 - YES price)
    trade_price = price if side == "BUY YES" else round(1.0 - price, 4)
    
    # Check for extreme liquidity risk (e.g. if NO is < 0.20)
    if trade_price < 0.20:
        return

    num_shares = round(entry_cost / trade_price, 4)
    portfolio["active_trades"][market_id] = {
        "question": question,
        "side": side,
        "yes_price_at_entry": round(price, 4), # Store YES price for reference
        "entry_price": round(trade_price, 4),   # Store actual token price
        "entry_cost": round(entry_cost, 2),
        "shares": num_shares,
        "coin": coin,
        "timeframe": timeframe,
        "entry_at": str(datetime.now())
    }
    
    portfolio["balance"] = round(portfolio["balance"] - entry_cost, 2)
    print(f"📄 PAPER TRADE: {side} {question[:40]} | Stake: ${round(entry_cost, 2)} @ {trade_price}")
    save_portfolio(portfolio)

def update_paper_trades(current_prices):
    """
    v21: PRECISION EXIT LOGIC
    - Uses actual token price for PnL
    - 15% Profit Target / 10% Stop Loss
    """
    portfolio = load_portfolio()
    TP_PCT = 0.15
    SL_PCT = 0.10
    
    closed_any = False
    to_delete = []
    
    for m_id, trade in portfolio["active_trades"].items():
        if m_id not in current_prices:
            continue
            
        cur_yes_price = current_prices[m_id]
        
        # Determine actual current price of the token we hold
        cur_trade_price = cur_yes_price if trade["side"] == "BUY YES" else round(1.0 - cur_yes_price, 4)
        
        entry = trade["entry_price"]
        
        # Calculate true move percentage
        move_pct = (cur_trade_price - entry) / entry
            
        if move_pct >= TP_PCT or move_pct <= -SL_PCT:
            # PnL is move_pct * entry_cost
            total_pnl = round(move_pct * trade["entry_cost"], 2)
            
            # Cap loss at the entry cost (but since we use SL_PCT=0.10, this is unlikely)
            total_pnl = max(total_pnl, -trade["entry_cost"])
            
            payout = round(trade["entry_cost"] + total_pnl, 2)
            
            trade["exit_price"] = round(cur_trade_price, 4)
            trade["yes_price_at_exit"] = round(cur_yes_price, 4)
            trade["exit_at"] = str(datetime.now())
            trade["pnl"] = total_pnl
            trade["move_pct"] = round(move_pct * 100, 2)
            
            portfolio["history"].append(trade)
            portfolio["balance"] = round(portfolio["balance"] + payout, 2)
            to_delete.append(m_id)
            closed_any = True
            
            status = "💰 PROFIT" if total_pnl > 0 else "🛑 STOP"
            print(f"📄 PAPER EXIT: {status} | PnL=${total_pnl} ({trade['move_pct']}%)")

    for m_id in to_delete:
        del portfolio["active_trades"][m_id]
        
    if closed_any:
        save_portfolio(portfolio)
