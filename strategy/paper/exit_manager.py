from datetime import datetime

from app.logger import get_logger
from strategy.paper.storage_adapter import (
    adjust_portfolio_balance,
    close_paper_trade,
    get_market_end_time,
    get_yes_price_at_close,
)
from strategy.paper.risk_manager import risk_profile_for_timeframe
from strategy.paper.state import load_portfolio

logger = get_logger()


def resolve_stale_exit(trade, end_time):
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


def _apply_close(trade, market_id, now, hold_seconds, resolved):
    trade["exit_price"] = resolved["exit_price"]
    trade["yes_price_at_exit"] = resolved["yes_price_at_exit"]
    trade["exit_at"] = str(now)
    trade["pnl"] = resolved["pnl"]
    trade["move_pct"] = resolved["move_pct"]
    trade["hold_seconds"] = int(hold_seconds)
    trade["exit_reason"] = resolved["exit_reason"]
    trade["market_id"] = market_id

    adjust_portfolio_balance(resolved["payout"])
    try:
        close_paper_trade(trade)
    except Exception as e:
        logger.warning(f"paper_trader: failed to close trade: {e}")
    logger.info(
        f"📄 PAPER EXIT: ↩ EARLY_EXIT:{trade['exit_reason']} | PnL=${trade['pnl']} ({trade['move_pct']}%)"
    )


def update_paper_trades(current_prices, market_state=None):
    portfolio = load_portfolio()
    max_hold_by_tf_sec = {
        "5m": 15 * 60,
        "15m": 45 * 60,
        "1h": 2 * 60 * 60,
        "4h": 6 * 60 * 60,
    }

    for market_id, trade in portfolio["active_trades"].items():
        now = datetime.now()
        entry_at = datetime.fromisoformat(trade["entry_at"])
        hold_seconds = (now - entry_at).total_seconds()
        timeframe = trade.get("timeframe", "5m")
        selected_risk = risk_profile_for_timeframe(timeframe)
        tp_pct = float(selected_risk.get("tp_pct", 0.12))
        sl_pct = float(selected_risk.get("sl_pct", 0.08))
        contextual_sl_enabled = bool(selected_risk.get("contextual_sl_enabled", False))
        non_dom_thresh = float(
            selected_risk.get("non_dominant_distance_threshold", 0.10)
        )
        non_dom_sl_pct = float(selected_risk.get("non_dominant_sl_pct", sl_pct))
        early_hold_seconds = int(selected_risk.get("early_hold_seconds", 90))
        early_sl_pct = float(selected_risk.get("early_sl_pct", sl_pct))
        unresolved_band = float(selected_risk.get("unresolved_band", 0.03))
        hold_time_stop_before_end_sec = int(
            selected_risk.get("hold_time_stop_before_end_sec", 45)
        )
        max_hold_sec = max_hold_by_tf_sec.get(timeframe, 15 * 60)
        end_time = trade.get("end_time")
        if end_time is None and market_state and market_id in market_state:
            end_time = market_state[market_id].get("end_time")
        if end_time is None:
            end_time = get_market_end_time(market_id)

        entry_ts = int(entry_at.timestamp())
        if end_time is None:
            try:
                end_time = entry_ts + int(max_hold_sec)
            except Exception as e:
                logger.warning(f"paper_trader: end_time fallback failed: {e}")
                end_time = None
        if end_time and int(end_time) <= entry_ts:
            end_time = entry_ts + int(max_hold_sec)
        if end_time:
            trade["end_time"] = int(end_time)

        if end_time and now.timestamp() > float(end_time) + 30:
            resolved = resolve_stale_exit(trade, end_time)
            _apply_close(trade, market_id, now, hold_seconds, resolved)
            continue

        if market_id not in current_prices:
            if end_time and now.timestamp() > float(end_time) + 30:
                resolved = resolve_stale_exit(trade, end_time)
                _apply_close(trade, market_id, now, hold_seconds, resolved)
            elif hold_seconds >= max_hold_sec:
                resolved = resolve_stale_exit(trade, end_time)
                _apply_close(trade, market_id, now, hold_seconds, resolved)
            continue

        cur_yes_price = current_prices[market_id]
        cur_trade_price = (
            cur_yes_price
            if trade["side"] == "BUY YES"
            else round(1.0 - cur_yes_price, 4)
        )
        entry = trade["entry_price"]
        move_pct = (cur_trade_price - entry) / entry

        effective_sl_pct = sl_pct
        if contextual_sl_enabled:
            entry_yes = float(
                trade.get(
                    "yes_price_at_entry",
                    entry if trade["side"] == "BUY YES" else round(1.0 - entry, 4),
                )
            )
            dominance = abs(entry_yes - 0.5)
            if dominance < non_dom_thresh:
                effective_sl_pct = min(effective_sl_pct, non_dom_sl_pct)
            if hold_seconds <= early_hold_seconds:
                effective_sl_pct = min(effective_sl_pct, early_sl_pct)

        early_reason = None
        if end_time:
            if now.timestamp() > float(end_time) + 30:
                early_reason = "TIME"
            else:
                remaining = float(end_time) - now.timestamp()
                if (
                    remaining <= hold_time_stop_before_end_sec
                    and abs(float(cur_yes_price) - 0.5) <= unresolved_band
                ):
                    early_reason = "TIME_UNRESOLVED"
        elif hold_seconds >= max_hold_sec:
            early_reason = "TIME"

        if market_state and market_id in market_state:
            state = market_state[market_id]
            pressure = state.get("pressure", 0.0)
            effective_ev = state.get("effective_ev")
            if effective_ev is not None and effective_ev < -0.01:
                early_reason = early_reason or "EV_FLIP"
            if trade["side"] == "BUY YES" and pressure < -0.20:
                early_reason = early_reason or "PRESSURE_FLIP"
            if trade["side"] == "BUY NO" and pressure > 0.20:
                early_reason = early_reason or "PRESSURE_FLIP"

        if move_pct >= tp_pct or move_pct <= -effective_sl_pct or early_reason:
            total_pnl = round(move_pct * trade["entry_cost"], 2)
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
                trade["exit_reason"] = "TP" if move_pct >= tp_pct else "SL"
            trade["market_id"] = market_id

            adjust_portfolio_balance(payout)
            try:
                close_paper_trade(trade)
            except Exception as e:
                logger.warning(f"paper_trader: failed to close trade: {e}")

            if early_reason:
                status = f"↩ EARLY_EXIT:{early_reason}"
            else:
                status = "💰 PROFIT" if total_pnl > 0 else "🛑 STOP"
            logger.info(
                f"📄 PAPER EXIT: {status} | PnL=${total_pnl} ({trade['move_pct']}%)"
            )
