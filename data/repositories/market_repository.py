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


def insert_external_spot_tick(conn, tick):
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO external_spot_ticks (
            ts_ms, venue, symbol, bid, ask, mid, spread, spread_bps,
            bid_size, ask_size, imbalance, momentum_10s, inserted_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(tick.get("ts_ms") or (now * 1000)),
            tick.get("venue", "binance_spot"),
            tick.get("symbol", "BTCUSDT"),
            tick.get("bid"),
            tick.get("ask"),
            tick.get("mid"),
            tick.get("spread"),
            tick.get("spread_bps"),
            tick.get("bid_size"),
            tick.get("ask_size"),
            tick.get("imbalance"),
            tick.get("momentum_10s"),
            now,
        ),
    )
    conn.commit()


def insert_perp_context_tick(conn, tick):
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO perp_context_ticks (
            ts_ms, venue, symbol, funding_rate, open_interest, oi_delta_1m,
            liq_long_1m, liq_short_1m, basis_bps, inserted_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(tick.get("ts_ms") or (now * 1000)),
            tick.get("venue", "binance_futures"),
            tick.get("symbol", "BTCUSDT"),
            tick.get("funding_rate"),
            tick.get("open_interest"),
            tick.get("oi_delta_1m"),
            tick.get("liq_long_1m"),
            tick.get("liq_short_1m"),
            tick.get("basis_bps"),
            now,
        ),
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


def get_latest_external_spot(conn, symbol="BTCUSDT", max_age_ms=15000):
    now_ms = int(time.time() * 1000)
    cur = conn.execute(
        """
        SELECT ts_ms, venue, symbol, bid, ask, mid, spread, spread_bps,
               bid_size, ask_size, imbalance, momentum_10s
        FROM external_spot_ticks
        WHERE symbol = ?
        ORDER BY ts_ms DESC
        LIMIT 1
        """,
        (symbol,),
    )
    row = cur.fetchone()
    if not row:
        return None
    if (now_ms - int(row[0])) > int(max_age_ms):
        return None
    return {
        "ts_ms": int(row[0]),
        "venue": row[1],
        "symbol": row[2],
        "bid": float(row[3]) if row[3] is not None else None,
        "ask": float(row[4]) if row[4] is not None else None,
        "mid": float(row[5]) if row[5] is not None else None,
        "spread": float(row[6]) if row[6] is not None else None,
        "spread_bps": float(row[7]) if row[7] is not None else None,
        "bid_size": float(row[8]) if row[8] is not None else None,
        "ask_size": float(row[9]) if row[9] is not None else None,
        "imbalance": float(row[10]) if row[10] is not None else None,
        "momentum_10s": float(row[11]) if row[11] is not None else None,
    }


def get_latest_perp_context(conn, symbol="BTCUSDT", max_age_ms=30000):
    now_ms = int(time.time() * 1000)
    cur = conn.execute(
        """
        SELECT ts_ms, venue, symbol, funding_rate, open_interest, oi_delta_1m,
               liq_long_1m, liq_short_1m, basis_bps
        FROM perp_context_ticks
        WHERE symbol = ?
        ORDER BY ts_ms DESC
        LIMIT 1
        """,
        (symbol,),
    )
    row = cur.fetchone()
    if not row:
        return None
    if (now_ms - int(row[0])) > int(max_age_ms):
        return None
    return {
        "ts_ms": int(row[0]),
        "venue": row[1],
        "symbol": row[2],
        "funding_rate": float(row[3]) if row[3] is not None else None,
        "open_interest": float(row[4]) if row[4] is not None else None,
        "oi_delta_1m": float(row[5]) if row[5] is not None else None,
        "liq_long_1m": float(row[6]) if row[6] is not None else None,
        "liq_short_1m": float(row[7]) if row[7] is not None else None,
        "basis_bps": float(row[8]) if row[8] is not None else None,
    }
