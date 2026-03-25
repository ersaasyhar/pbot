from datetime import datetime

from app.logger import get_logger
from strategy.paper.risk_manager import calculate_stake
from strategy.paper.storage_adapter import (
    adjust_portfolio_balance,
    upsert_paper_trade_entry,
)
from strategy.paper.state import load_portfolio

logger = get_logger()


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
    portfolio = load_portfolio()
    if market_id in portfolio["active_trades"]:
        return False

    now = datetime.now()
    daily_pnl = sum(
        [
            t["pnl"]
            for t in portfolio.get("history", [])
            if (now - datetime.fromisoformat(t["exit_at"])).total_seconds() < 86400
        ]
    )
    if daily_pnl <= -50.0:
        return False

    active = portfolio["active_trades"].values()
    coin_count = len([t for t in active if t["coin"] == coin])
    if coin_count >= 1:
        return False

    side_count = len([t for t in active if t["side"] == side])
    if side_count >= 3:
        return False

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
        logger.warning(f"paper_trader: failed to upsert entry: {e}")

    logger.info(
        f"📄 SNIPER TRADE: {side} ({int(confidence * 100)}%) {question[:30]}... "
        f"| Stake: ${round(entry_cost, 2)} @ {trade_price}"
    )
    return True
