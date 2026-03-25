import time


def trade_row_to_dict(row):
    return {
        "trade_id": row[0],
        "market_id": row[1],
        "question": row[2],
        "side": row[3],
        "coin": row[4],
        "timeframe": row[5],
        "confidence": row[6],
        "effective_ev_at_entry": row[7],
        "regime_at_entry": row[8],
        "signal_age_sec": row[9],
        "yes_price_at_entry": row[10],
        "entry_price": row[11],
        "entry_cost": row[12],
        "shares": row[13],
        "entry_at": row[14],
        "end_time": row[15],
        "exit_price": row[16],
        "yes_price_at_exit": row[17],
        "exit_at": row[18],
        "pnl": row[19],
        "move_pct": row[20],
        "hold_seconds": row[21],
        "exit_reason": row[22],
        "status": row[23],
    }


def ensure_trade_id(trade, fallback_prefix="trade"):
    existing = trade.get("trade_id")
    if existing:
        return str(existing)
    market_id = str(trade.get("market_id") or fallback_prefix)
    entry_at = str(trade.get("entry_at") or "")
    if entry_at:
        return f"{market_id}:{entry_at}"
    return f"{market_id}:{int(time.time() * 1000)}"
