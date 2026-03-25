import sqlite3
import time

from data.db_config import DB_PATH
from data.repositories.trade_repository import trade_row_to_dict


def load_paper_portfolio_snapshot(history_limit=5000):
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT initial_balance, balance, high_water_mark
            FROM paper_portfolio_state
            WHERE id=1
            """
        )
        row = cur.fetchone()
        if row:
            initial_balance, balance, high_water_mark = row
        else:
            initial_balance, balance, high_water_mark = (1000.0, 1000.0, 1000.0)

        cur.execute(
            """
            SELECT
                trade_id, market_id, question, side, coin, timeframe,
                confidence, effective_ev_at_entry, regime_at_entry, signal_age_sec,
                yes_price_at_entry, entry_price, entry_cost, shares, entry_at,
                end_time, exit_price, yes_price_at_exit, exit_at, pnl, move_pct, hold_seconds,
                exit_reason, status
            FROM paper_trades
            WHERE status='OPEN'
            ORDER BY entry_at ASC
            """
        )
        active_rows = cur.fetchall()
        active = {}
        for r in active_rows:
            t = trade_row_to_dict(r)
            market_id = t.get("market_id")
            if market_id:
                active[market_id] = t

        cur.execute(
            """
            SELECT
                trade_id, market_id, question, side, coin, timeframe,
                confidence, effective_ev_at_entry, regime_at_entry, signal_age_sec,
                yes_price_at_entry, entry_price, entry_cost, shares, entry_at,
                end_time, exit_price, yes_price_at_exit, exit_at, pnl, move_pct, hold_seconds,
                exit_reason, status
            FROM paper_trades
            WHERE status='CLOSED'
            ORDER BY updated_ts DESC
            LIMIT ?
            """,
            (int(history_limit),),
        )
        closed_rows = cur.fetchall()
        history = [trade_row_to_dict(r) for r in closed_rows]
        history.reverse()

    return {
        "initial_balance": float(initial_balance),
        "balance": float(balance),
        "high_water_mark": float(high_water_mark),
        "active_trades": active,
        "history": history,
    }


def get_recent_closed_trades(limit=2000):
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                trade_id, market_id, question, side, coin, timeframe,
                confidence, effective_ev_at_entry, regime_at_entry, signal_age_sec,
                yes_price_at_entry, entry_price, entry_cost, shares, entry_at,
                end_time, exit_price, yes_price_at_exit, exit_at, pnl, move_pct, hold_seconds,
                exit_reason, status
            FROM paper_trades
            WHERE status='CLOSED'
            ORDER BY updated_ts DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = cur.fetchall()
    return [trade_row_to_dict(r) for r in rows]


def adjust_portfolio_balance(delta, allow_negative=False):
    now = int(time.time())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT initial_balance, balance, high_water_mark
            FROM paper_portfolio_state
            WHERE id=1
            """
        )
        row = cur.fetchone()
        if not row:
            initial_balance, balance, high_water_mark = (1000.0, 1000.0, 1000.0)
            cur.execute(
                """
                INSERT INTO paper_portfolio_state (id, initial_balance, balance, high_water_mark, updated_ts)
                VALUES (1, ?, ?, ?, ?)
                """,
                (initial_balance, balance, high_water_mark, now),
            )
        else:
            initial_balance, balance, high_water_mark = row

        new_balance = float(balance) + float(delta)
        if (not allow_negative) and new_balance < 0:
            return None
        new_high = max(float(high_water_mark), new_balance)

        cur.execute(
            """
            UPDATE paper_portfolio_state
            SET balance=?, high_water_mark=?, updated_ts=?
            WHERE id=1
            """,
            (new_balance, new_high, now),
        )
        conn.commit()
    return {
        "initial_balance": float(initial_balance),
        "balance": float(new_balance),
        "high_water_mark": float(new_high),
    }


def upsert_paper_trade_entry(trade):
    now = int(time.time())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            INSERT INTO paper_trades (
                trade_id, market_id, question, side, coin, timeframe,
                confidence, effective_ev_at_entry, regime_at_entry, signal_age_sec,
                yes_price_at_entry, entry_price, entry_cost, shares, entry_at, end_time,
                status, created_ts, updated_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO UPDATE SET
                market_id=excluded.market_id,
                question=excluded.question,
                side=excluded.side,
                coin=excluded.coin,
                timeframe=excluded.timeframe,
                confidence=excluded.confidence,
                effective_ev_at_entry=excluded.effective_ev_at_entry,
                regime_at_entry=excluded.regime_at_entry,
                signal_age_sec=excluded.signal_age_sec,
                yes_price_at_entry=excluded.yes_price_at_entry,
                entry_price=excluded.entry_price,
                entry_cost=excluded.entry_cost,
                shares=excluded.shares,
                entry_at=excluded.entry_at,
                end_time=excluded.end_time,
                status='OPEN',
                updated_ts=excluded.updated_ts
            """,
            (
                trade.get("trade_id"),
                trade.get("market_id"),
                trade.get("question"),
                trade.get("side"),
                trade.get("coin"),
                trade.get("timeframe"),
                trade.get("confidence"),
                trade.get("effective_ev_at_entry"),
                trade.get("regime_at_entry"),
                trade.get("signal_age_sec"),
                trade.get("yes_price_at_entry"),
                trade.get("entry_price"),
                trade.get("entry_cost"),
                trade.get("shares"),
                trade.get("entry_at"),
                trade.get("end_time"),
                "OPEN",
                now,
                now,
            ),
        )
        conn.commit()


def close_paper_trade(trade):
    now = int(time.time())
    trade_id = trade.get("trade_id")
    if not trade_id:
        return
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            UPDATE paper_trades
            SET
                exit_price=?,
                yes_price_at_exit=?,
                exit_at=?,
                pnl=?,
                move_pct=?,
                hold_seconds=?,
                exit_reason=?,
                status='CLOSED',
                updated_ts=?
            WHERE trade_id=?
            """,
            (
                trade.get("exit_price"),
                trade.get("yes_price_at_exit"),
                trade.get("exit_at"),
                trade.get("pnl"),
                trade.get("move_pct"),
                trade.get("hold_seconds"),
                trade.get("exit_reason"),
                now,
                trade_id,
            ),
        )
        conn.commit()


def reset_paper_trading_state(initial_balance=1000.0):
    now = int(time.time())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("DELETE FROM paper_trades")
        conn.execute(
            """
            INSERT INTO paper_portfolio_state (id, initial_balance, balance, high_water_mark, updated_ts)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                initial_balance=excluded.initial_balance,
                balance=excluded.balance,
                high_water_mark=excluded.high_water_mark,
                updated_ts=excluded.updated_ts
            """,
            (
                float(initial_balance),
                float(initial_balance),
                float(initial_balance),
                now,
            ),
        )
        conn.commit()
