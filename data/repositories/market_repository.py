import sqlite3
import time

from app.logger import get_logger
from data.db_config import DB_PATH


def insert_market(conn, market):
    conn.execute(
        """
        INSERT INTO market_prices (market_id, condition_id, clob_token_id, question, price, volume, open_interest, coin, timeframe, end_time, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            market.get("market_id"),
            market.get("condition_id"),
            market.get("clob_token_id"),
            market.get("question"),
            market.get("price"),
            market.get("volume"),
            market.get("open_interest", 0.0),
            market.get("coin"),
            market.get("timeframe"),
            market.get("end_time"),
            market.get("timestamp"),
        ),
    )
    conn.commit()


def insert_ws_ticks_bulk(conn, ticks):
    if not ticks:
        return
    now = int(time.time())
    rows = []
    for t in ticks:
        rows.append(
            (
                int(t.get("ts_ms") or (now * 1000)),
                t.get("event_type"),
                t.get("token_id"),
                t.get("market_id"),
                t.get("coin"),
                t.get("timeframe"),
                t.get("best_bid"),
                t.get("best_ask"),
                t.get("mid"),
                t.get("spread"),
                t.get("bid_sz_top5"),
                t.get("ask_sz_top5"),
                t.get("depth_top5"),
                t.get("pressure"),
                t.get("last_trade_price"),
                now,
            )
        )
    conn.executemany(
        """
        INSERT INTO ws_ticks (
            ts_ms, event_type, token_id, market_id, coin, timeframe,
            best_bid, best_ask, mid, spread,
            bid_sz_top5, ask_sz_top5, depth_top5, pressure, last_trade_price,
            inserted_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def get_market_end_time(market_id):
    if not market_id:
        return None
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT end_time FROM market_prices WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                (str(market_id),),
            )
            row = cur.fetchone()
        except Exception as e:
            get_logger().debug(f"storage: get_market_end_time failed: {e}")
            return None
    if not row:
        return None
    try:
        return int(row[0]) if row[0] is not None else None
    except Exception as e:
        get_logger().debug(f"storage: invalid end_time value: {e}")
        return None


def get_yes_price_at_close(market_id, end_time, grace_sec=120):
    if not market_id or not end_time:
        return None, None
    try:
        end_ts = int(end_time)
    except Exception as e:
        get_logger().debug(f"storage: invalid end_time in get_yes_price_at_close: {e}")
        return None, None

    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT price, timestamp
                FROM market_prices
                WHERE market_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                ORDER BY timestamp ASC
                LIMIT 1
                """,
                (str(market_id), end_ts, end_ts + int(grace_sec)),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return float(row[0]), "AFTER_END"

            cur.execute(
                """
                SELECT price, timestamp
                FROM market_prices
                WHERE market_id = ?
                  AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (str(market_id), end_ts),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return float(row[0]), "BEFORE_END"
        except Exception as e:
            get_logger().debug(f"storage: get_yes_price_at_close failed: {e}")
            return None, None
    return None, None


def get_recent_prices(conn, market_id, limit=20):
    cur = conn.execute(
        """
        SELECT price FROM market_prices
        WHERE market_id = ?
        ORDER BY id DESC
        LIMIT ?
    """,
        (market_id, limit),
    )

    rows = cur.fetchall()
    return [float(r[0]) for r in reversed(rows)]


def get_recent_oi(conn, market_id, limit=10):
    cur = conn.execute(
        """
        SELECT open_interest FROM market_prices
        WHERE market_id = ?
        ORDER BY id DESC
        LIMIT ?
    """,
        (market_id, limit),
    )

    rows = cur.fetchall()
    return [float(r[0]) for r in reversed(rows)]


def get_last_price(conn, market_id):
    cur = conn.execute(
        """
        SELECT price, volume FROM market_prices
        WHERE market_id = ?
        ORDER BY id DESC
        LIMIT 1
    """,
        (market_id,),
    )

    row = cur.fetchone()
    if not row:
        return None

    return {"price": float(row[0]), "volume": float(row[1])}
