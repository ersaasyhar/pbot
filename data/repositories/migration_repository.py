import json
import os
import sqlite3
import time

from app.logger import get_logger
from data.db_config import DB_PATH
from data.repositories.trade_repository import ensure_trade_id


def migrate_legacy_json_portfolio(path="db/paper_portfolio.json"):
    if not os.path.exists(path):
        return

    try:
        with open(path, "r") as f:
            payload = json.load(f)
    except Exception as e:
        get_logger().warning(f"storage: failed to read legacy portfolio: {e}")
        return

    active = payload.get("active_trades", {}) or {}
    history = payload.get("history", []) or []
    bal = float(payload.get("balance", 1000.0) or 1000.0)
    hwm = float(payload.get("high_water_mark", max(1000.0, bal)) or max(1000.0, bal))
    now = int(time.time())

    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM paper_trades")
        existing = int(cur.fetchone()[0])
        if existing > 0:
            return

        cur.execute(
            """
            UPDATE paper_portfolio_state
            SET balance=?, high_water_mark=?, updated_ts=?
            WHERE id=1
            """,
            (bal, hwm, now),
        )

        def insert_trade(t, status):
            local = dict(t)
            local["trade_id"] = ensure_trade_id(local, "legacy")
            conn.execute(
                """
                INSERT INTO paper_trades (
                    trade_id, market_id, question, side, coin, timeframe,
                    confidence, effective_ev_at_entry, regime_at_entry, signal_age_sec,
                    yes_price_at_entry, entry_price, entry_cost, shares, entry_at, end_time,
                    exit_price, yes_price_at_exit, exit_at, pnl, move_pct, hold_seconds,
                    exit_reason, status, created_ts, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id) DO NOTHING
                """,
                (
                    local.get("trade_id"),
                    local.get("market_id"),
                    local.get("question"),
                    local.get("side"),
                    local.get("coin"),
                    local.get("timeframe"),
                    local.get("confidence"),
                    local.get("effective_ev_at_entry"),
                    local.get("regime_at_entry"),
                    local.get("signal_age_sec"),
                    local.get("yes_price_at_entry"),
                    local.get("entry_price"),
                    local.get("entry_cost"),
                    local.get("shares"),
                    local.get("entry_at"),
                    local.get("end_time"),
                    local.get("exit_price"),
                    local.get("yes_price_at_exit"),
                    local.get("exit_at"),
                    local.get("pnl"),
                    local.get("move_pct"),
                    local.get("hold_seconds"),
                    local.get("exit_reason"),
                    status,
                    now,
                    now,
                ),
            )

        for _, t in active.items():
            insert_trade(t, "OPEN")
        for t in history:
            insert_trade(t, "CLOSED")
        conn.commit()

    backup = f"{path}.migrated"
    try:
        os.replace(path, backup)
    except Exception as e:
        get_logger().warning(f"storage: failed to rename legacy portfolio: {e}")
