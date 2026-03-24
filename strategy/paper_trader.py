from datetime import datetime
from data.storage import (
    upsert_paper_trade_entry,
    close_paper_trade,
    load_paper_portfolio_snapshot,
    adjust_portfolio_balance,
    get_market_end_time,
    get_yes_price_at_close,
)
from app.logger import get_logger
from app.config import (
    SIZING_PROFILES,
    RISK_PROFILES,
    SELECTED_RISK_PROFILE_NAME,
)


def load_portfolio():
    return load_paper_portfolio_snapshot(history_limit=5000)


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


def _risk_profile_for_timeframe(timeframe):
    base = RISK_PROFILES.get(SELECTED_RISK_PROFILE_NAME, {}) or {}
    overrides = (base.get("timeframe_overrides", {}) or {}).get(timeframe, {}) or {}
    if not overrides:
        return base
    merged = dict(base)
    merged.update(overrides)
    return merged


def _resolve_stale_exit(trade, end_time):
    entry_trade_price = float(trade["entry_price"])
    entry_cost = float(trade["entry_cost"])
    yes_price, source = get_yes_price_at_close(trade.get("market_id"), end_time)
    if yes_price is None:
        yes_price = float(
            trade.get(
                "yes_price_at_entry",
                entry_trade_price
                if trade["side"] == "BUY YES"
                else round(1.0 - entry_trade_price, 4),
            )
        )
        source = "ENTRY_FALLBACK"

    exit_trade_price = (
        yes_price if trade["side"] == "BUY YES" else round(1.0 - yes_price, 4)
    )
    move_pct = (exit_trade_price - entry_trade_price) / entry_trade_price
    total_pnl = round(move_pct * entry_cost, 2)
    total_pnl = max(total_pnl, -entry_cost)
    payout = round(entry_cost + total_pnl, 2)
    return {
        "exit_price": round(exit_trade_price, 4),
        "yes_price_at_exit": round(yes_price, 4),
        "pnl": total_pnl,
        "move_pct": round(move_pct * 100, 2),
        "exit_reason": f"STALE_TIMEOUT_{source}",
        "payout": payout,
    }


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
    end_time=None,
):
    """
    v25: DYNAMIC SIZING + CIRCUIT BREAKER
    - Position size scales with signal confidence (0.5x to 1.0x)
    - Circuit Breaker: Stop if daily loss > $50
    """
    portfolio = load_portfolio()
    if market_id in portfolio["active_trades"]:
        return False

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
        return False

    # --- CORRELATION GUARD ---
    active = portfolio["active_trades"].values()

    # 1. Coin Limit
    coin_count = len([t for t in active if t["coin"] == coin])
    if coin_count >= 1:
        return False

    # 2. Side Limit
    side_count = len([t for t in active if t["side"] == side])
    if side_count >= 3:
        return False

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
        return False

    entry_cost = calculate_stake(portfolio, sizing_profile, confidence)
    if entry_cost < 1.0 or entry_cost > portfolio["balance"]:
        return False

    now = datetime.now()
    trade_id = f"{market_id}:{int(now.timestamp() * 1000)}"
    num_shares = round(entry_cost / trade_price, 4)
    trade_payload = {
        "trade_id": trade_id,
        "market_id": market_id,
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
        "entry_at": str(now),
        "end_time": int(end_time) if end_time else None,
    }
    balance_state = adjust_portfolio_balance(-entry_cost)
    if balance_state is None:
        return False
    try:
        upsert_paper_trade_entry(trade_payload)
    except Exception as e:
        get_logger().warning(f"paper_trader: failed to upsert entry: {e}")

    print(
        f"📄 SNIPER TRADE: {side} ({int(confidence * 100)}%) {question[:30]}... "
        f"| Stake: ${round(entry_cost, 2)} @ {trade_price}"
    )
    return True


def update_paper_trades(current_prices, market_state=None):
    """
    v23: SNIPER EXIT LOGIC
    - 10% Profit Target
    - 5% Stop Loss (Very tight for capital preservation)
    """
    portfolio = load_portfolio()
    max_hold_by_tf_sec = {
        "5m": 15 * 60,
        "15m": 45 * 60,
        "1h": 2 * 60 * 60,
        "4h": 6 * 60 * 60,
    }

    for m_id, trade in portfolio["active_trades"].items():
        now = datetime.now()
        entry_at = datetime.fromisoformat(trade["entry_at"])
        hold_seconds = (now - entry_at).total_seconds()
        timeframe = trade.get("timeframe", "5m")
        selected_risk = _risk_profile_for_timeframe(timeframe)
        TP_PCT = float(selected_risk.get("tp_pct", 0.12))
        SL_PCT = float(selected_risk.get("sl_pct", 0.08))
        max_hold_sec = max_hold_by_tf_sec.get(timeframe, 15 * 60)
        end_time = trade.get("end_time")
        if end_time is None and market_state and m_id in market_state:
            end_time = market_state[m_id].get("end_time")
        if end_time is None:
            end_time = get_market_end_time(m_id)
        entry_ts = int(entry_at.timestamp())
        if end_time is None:
            # Fallback: approximate session end using entry time + timeframe window.
            try:
                end_time = entry_ts + int(max_hold_sec)
            except Exception as e:
                get_logger().warning(f"paper_trader: end_time fallback failed: {e}")
                end_time = None
        # Guard: if end_time is behind entry, use entry-based window instead.
        if end_time and int(end_time) <= entry_ts:
            end_time = entry_ts + int(max_hold_sec)
        if end_time:
            trade["end_time"] = int(end_time)
        if end_time and now.timestamp() > float(end_time) + 30:
            # Event ended; force close and release balance.
            resolved = _resolve_stale_exit(trade, end_time)
            trade["exit_price"] = resolved["exit_price"]
            trade["yes_price_at_exit"] = resolved["yes_price_at_exit"]
            trade["exit_at"] = str(now)
            trade["pnl"] = resolved["pnl"]
            trade["move_pct"] = resolved["move_pct"]
            trade["hold_seconds"] = int(hold_seconds)
            trade["exit_reason"] = resolved["exit_reason"]
            trade["market_id"] = m_id

            adjust_portfolio_balance(resolved["payout"])
            try:
                close_paper_trade(trade)
            except Exception as e:
                get_logger().warning(f"paper_trader: failed to close trade: {e}")
            print(
                f"📄 PAPER EXIT: ↩ EARLY_EXIT:{trade['exit_reason']} | PnL=${trade['pnl']} ({trade['move_pct']}%)"
            )
            continue

        if m_id not in current_prices:
            # Market is no longer streaming (often ended). Avoid stale lock:
            # force-close once the trade exceeded its max hold horizon.
            if end_time and now.timestamp() > float(end_time) + 30:
                resolved = _resolve_stale_exit(trade, end_time)
                trade["exit_price"] = resolved["exit_price"]
                trade["yes_price_at_exit"] = resolved["yes_price_at_exit"]
                trade["exit_at"] = str(now)
                trade["pnl"] = resolved["pnl"]
                trade["move_pct"] = resolved["move_pct"]
                trade["hold_seconds"] = int(hold_seconds)
                trade["exit_reason"] = resolved["exit_reason"]
                trade["market_id"] = m_id

                adjust_portfolio_balance(resolved["payout"])
                try:
                    close_paper_trade(trade)
                except Exception as e:
                    get_logger().warning(f"paper_trader: failed to close trade: {e}")
                print(
                    f"📄 PAPER EXIT: ↩ EARLY_EXIT:{trade['exit_reason']} | PnL=${trade['pnl']} ({trade['move_pct']}%)"
                )
            elif hold_seconds >= max_hold_sec:
                resolved = _resolve_stale_exit(trade, end_time)
                trade["exit_price"] = resolved["exit_price"]
                trade["yes_price_at_exit"] = resolved["yes_price_at_exit"]
                trade["exit_at"] = str(now)
                trade["pnl"] = resolved["pnl"]
                trade["move_pct"] = resolved["move_pct"]
                trade["hold_seconds"] = int(hold_seconds)
                trade["exit_reason"] = resolved["exit_reason"]
                trade["market_id"] = m_id

                adjust_portfolio_balance(resolved["payout"])
                try:
                    close_paper_trade(trade)
                except Exception as e:
                    get_logger().warning(f"paper_trader: failed to close trade: {e}")
                print(
                    f"📄 PAPER EXIT: ↩ EARLY_EXIT:{trade['exit_reason']} | PnL=${trade['pnl']} ({trade['move_pct']}%)"
                )
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
        if end_time:
            if now.timestamp() > float(end_time) + 30:
                early_reason = "TIME"
        elif hold_seconds >= max_hold_sec:
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
            trade["market_id"] = m_id

            adjust_portfolio_balance(payout)
            try:
                close_paper_trade(trade)
            except Exception as e:
                get_logger().warning(f"paper_trader: failed to close trade: {e}")

            if early_reason:
                status = f"↩ EARLY_EXIT:{early_reason}"
            else:
                status = "💰 PROFIT" if total_pnl > 0 else "🛑 STOP"
            print(f"📄 PAPER EXIT: {status} | PnL=${total_pnl} ({trade['move_pct']}%)")
