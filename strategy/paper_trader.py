import json
import os
from datetime import datetime
from app.config import SIZING_PROFILES

# Path to virtual state
STATE_PATH = "db/paper_portfolio.json"


def load_portfolio():
    if not os.path.exists(STATE_PATH):
        return {
            "balance": 1000.0,
            "high_water_mark": 1000.0,
            "active_trades": {},
            "history": [],
        }
    with open(STATE_PATH, "r") as f:
        data = json.load(f)
        if "high_water_mark" not in data:
            data["high_water_mark"] = max(1000.0, data.get("balance", 1000.0))
        return data


def save_portfolio(data):
    with open(STATE_PATH, "w") as f:
        json.dump(data, f, indent=4)


def calculate_stake(portfolio, sizing_profile_name, confidence=1.0):
    profile = SIZING_PROFILES.get(sizing_profile_name, SIZING_PROFILES.get("FIXED"))
    base_value = 0
    if profile["type"] == "fixed":
        base_value = float(profile["value"])
    else:
        base_value = round(portfolio["balance"] * profile["value"], 2)

    # --- DRAWDOWN GUARD ---
    high_water = portfolio.get("high_water_mark", 1000.0)
    current_bal = portfolio["balance"]

    drawdown_pct = 0.0
    if high_water > 0 and current_bal < high_water:
        drawdown_pct = (high_water - current_bal) / high_water

    # Scale down the bet size based on the depth of the drawdown
    drawdown_penalty = 1.0
    if drawdown_pct >= 0.10:  # 10% drawdown
        drawdown_penalty = 0.20  # Bet 80% less
    elif drawdown_pct >= 0.05:  # 5% drawdown
        drawdown_penalty = 0.50  # Bet 50% less
    elif drawdown_pct >= 0.02:  # 2% drawdown
        drawdown_penalty = 0.80  # Bet 20% less

    # Dynamic Sizing: Scale stake by confidence and drawdown penalty
    return round(base_value * confidence * drawdown_penalty, 2)


def execute_virtual_trade(
    market_id,
    question,
    side,
    price,
    coin,
    timeframe,
    sizing_profile="FIXED",
    confidence=1.0,
    effective_ev=None,
    regime=None,
    signal_age_sec=None,
):
    """
    v25: DYNAMIC SIZING + CIRCUIT BREAKER
    - Position size scales with signal confidence (0.5x to 1.0x)
    - Circuit Breaker: Stop if daily loss > $50
    """
    portfolio = load_portfolio()
    if market_id in portfolio["active_trades"]:
        return

    # --- CIRCUIT BREAKER ---
    # Max daily loss check (5% of $1000)
    now = datetime.now()
    daily_pnl = sum(
        [
            t["pnl"]
            for t in portfolio.get("history", [])
            if (now - datetime.fromisoformat(t["exit_at"])).total_seconds() < 86400
        ]
    )

    if daily_pnl <= -50.0:
        # print(f"🛑 CIRCUIT BREAKER ACTIVE: Daily PnL is {daily_pnl}")
        return

    # --- CORRELATION GUARD ---
    active = portfolio["active_trades"].values()

    # 1. Coin Limit
    coin_count = len([t for t in active if t["coin"] == coin])
    if coin_count >= 1:
        return

    # 2. Side Limit
    side_count = len([t for t in active if t["side"] == side])
    if side_count >= 3:
        return

    # --- SLIPPAGE SIMULATION ---
    slippage_pct = 0.005
    actual_entry_price = (
        price * (1.0 + slippage_pct)
        if side == "BUY YES"
        else price * (1.0 - slippage_pct)
    )

    trade_price = (
        actual_entry_price if side == "BUY YES" else round(1.0 - actual_entry_price, 4)
    )

    if trade_price < 0.20 or trade_price > 0.80:
        return

    entry_cost = calculate_stake(portfolio, sizing_profile, confidence)
    if entry_cost < 1.0 or entry_cost > portfolio["balance"]:
        return

    num_shares = round(entry_cost / trade_price, 4)
    portfolio["active_trades"][market_id] = {
        "question": question,
        "side": side,
        "confidence": confidence,
        "effective_ev_at_entry": effective_ev,
        "regime_at_entry": regime,
        "signal_age_sec": signal_age_sec,
        "yes_price_at_entry": round(actual_entry_price, 4),
        "entry_price": round(trade_price, 4),
        "entry_cost": round(entry_cost, 2),
        "shares": num_shares,
        "coin": coin,
        "timeframe": timeframe,
        "entry_at": str(datetime.now()),
    }

    portfolio["balance"] = round(portfolio["balance"] - entry_cost, 2)
    print(
        f"📄 SNIPER TRADE: {side} ({int(confidence * 100)}%) {question[:30]}... "
        f"| Stake: ${round(entry_cost, 2)} @ {trade_price}"
    )
    save_portfolio(portfolio)


def update_paper_trades(current_prices, market_state=None):
    """
    v23: SNIPER EXIT LOGIC
    - 10% Profit Target
    - 5% Stop Loss (Very tight for capital preservation)
    """
    portfolio = load_portfolio()
    TP_PCT = 0.10
    SL_PCT = 0.05

    closed_any = False
    to_delete = []
    max_hold_by_tf_sec = {
        "5m": 15 * 60,
        "15m": 45 * 60,
        "1h": 2 * 60 * 60,
        "4h": 6 * 60 * 60,
    }

    for m_id, trade in portfolio["active_trades"].items():
        if m_id not in current_prices:
            continue

        cur_yes_price = current_prices[m_id]

        # Determine actual current price of the token we hold
        cur_trade_price = (
            cur_yes_price
            if trade["side"] == "BUY YES"
            else round(1.0 - cur_yes_price, 4)
        )

        entry = trade["entry_price"]

        # Calculate true move percentage
        move_pct = (cur_trade_price - entry) / entry

        early_reason = None
        now = datetime.now()
        entry_at = datetime.fromisoformat(trade["entry_at"])
        hold_seconds = (now - entry_at).total_seconds()
        max_hold_sec = max_hold_by_tf_sec.get(trade.get("timeframe", "5m"), 15 * 60)

        if hold_seconds >= max_hold_sec:
            early_reason = "TIME"

        if market_state and m_id in market_state:
            state = market_state[m_id]
            pressure = state.get("pressure", 0.0)
            effective_ev = state.get("effective_ev")
            if effective_ev is not None and effective_ev < -0.01:
                early_reason = early_reason or "EV_FLIP"
            if trade["side"] == "BUY YES" and pressure < -0.20:
                early_reason = early_reason or "PRESSURE_FLIP"
            if trade["side"] == "BUY NO" and pressure > 0.20:
                early_reason = early_reason or "PRESSURE_FLIP"

        if move_pct >= TP_PCT or move_pct <= -SL_PCT or early_reason:
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
            trade["hold_seconds"] = int(hold_seconds)
            if early_reason:
                trade["exit_reason"] = early_reason
            else:
                trade["exit_reason"] = "TP" if move_pct >= TP_PCT else "SL"

            portfolio["history"].append(trade)
            portfolio["balance"] = round(portfolio["balance"] + payout, 2)

            # Update High Water Mark
            if portfolio["balance"] > portfolio.get("high_water_mark", 1000.0):
                portfolio["high_water_mark"] = portfolio["balance"]

            to_delete.append(m_id)
            closed_any = True

            if early_reason:
                status = f"↩ EARLY_EXIT:{early_reason}"
            else:
                status = "💰 PROFIT" if total_pnl > 0 else "🛑 STOP"
            print(f"📄 PAPER EXIT: {status} | PnL=${total_pnl} ({trade['move_pct']}%)")

    for m_id in to_delete:
        del portfolio["active_trades"][m_id]

    if closed_any:
        save_portfolio(portfolio)
