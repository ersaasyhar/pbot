
import sqlite3
import os
import time
import json
from app.logger import get_logger

DB_PATH = "db/market_v5.db"


def init_db():
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000")

    # Updated schema with condition_id and open_interest
    c.execute("""
    CREATE TABLE IF NOT EXISTS market_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id TEXT,
        condition_id TEXT,
        clob_token_id TEXT,
        question TEXT,
        price REAL,
        volume REAL,
        open_interest REAL,
        coin TEXT,
        timeframe TEXT,
        end_time INTEGER,
        timestamp INTEGER
    )
    """)
    # Backfill end_time column if upgrading existing DB.
    try:
        c.execute("ALTER TABLE market_prices ADD COLUMN end_time INTEGER")
    except Exception as e:
        get_logger().debug(f"storage: market_prices end_time column add skipped: {e}")

    # Lightweight WS recorder table (microstructure snapshots for replay).
    c.execute("""
    CREATE TABLE IF NOT EXISTS ws_ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms INTEGER,
        event_type TEXT,
        token_id TEXT,
        market_id TEXT,
        coin TEXT,
        timeframe TEXT,
        best_bid REAL,
        best_ask REAL,
        mid REAL,
        spread REAL,
        bid_sz_top5 REAL,
        ask_sz_top5 REAL,
        depth_top5 REAL,
        pressure REAL,
        last_trade_price REAL,
        inserted_ts INTEGER
    )
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_ws_ticks_ts ON ws_ticks(ts_ms)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_ws_ticks_token_ts ON ws_ticks(token_id, ts_ms)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_ws_ticks_coin_tf_ts ON ws_ticks(coin, timeframe, ts_ms)"
    )

    # Durable SQL mirror of paper trades (JSON remains as primary state for now).
    c.execute("""
    CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT UNIQUE,
        market_id TEXT,
        question TEXT,
        side TEXT,
        coin TEXT,
        timeframe TEXT,
        confidence REAL,
        effective_ev_at_entry REAL,
        regime_at_entry TEXT,
        signal_age_sec INTEGER,
        yes_price_at_entry REAL,
        entry_price REAL,
        entry_cost REAL,
        shares REAL,
        entry_at TEXT,
        end_time INTEGER,
        exit_price REAL,
        yes_price_at_exit REAL,
        exit_at TEXT,
        pnl REAL,
        move_pct REAL,
        hold_seconds INTEGER,
        exit_reason TEXT,
        status TEXT,
        created_ts INTEGER,
        updated_ts INTEGER
    )
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_trades_status_entry ON paper_trades(status, entry_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_trades_coin_tf ON paper_trades(coin, timeframe)"
    )
    # Backfill new column if upgrading existing DB.
    try:
        c.execute("ALTER TABLE paper_trades ADD COLUMN end_time INTEGER")
    except Exception as e:
        get_logger().debug(f"storage: paper_trades end_time column add skipped: {e}")

    # Source-of-truth state for paper portfolio.
    c.execute("""
    CREATE TABLE IF NOT EXISTS paper_portfolio_state (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        initial_balance REAL NOT NULL,
        balance REAL NOT NULL,
        high_water_mark REAL NOT NULL,
        updated_ts INTEGER NOT NULL
    )
    """)
    now = int(time.time())
    c.execute(
        """
        INSERT INTO paper_portfolio_state (id, initial_balance, balance, high_water_mark, updated_ts)
        VALUES (1, 1000.0, 1000.0, 1000.0, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (now,),
    )

    conn.commit()
    conn.close()
    migrate_legacy_json_portfolio()


# ✅ Insert full market snapshot
def insert_market(conn, market):
    # We use the existing connection passed from the engine
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


def _trade_row_to_dict(row):
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


def _ensure_trade_id(trade, fallback_prefix="trade"):
    existing = trade.get("trade_id")
    if existing:
        return str(existing)
    market_id = str(trade.get("market_id") or fallback_prefix)
    entry_at = str(trade.get("entry_at") or "")
    if entry_at:
        return f"{market_id}:{entry_at}"
    return f"{market_id}:{int(time.time() * 1000)}"


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
            t = _trade_row_to_dict(r)
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
        history = [_trade_row_to_dict(r) for r in closed_rows]
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
    return [_trade_row_to_dict(r) for r in rows]


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
            local["trade_id"] = _ensure_trade_id(local, "legacy")
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
            (float(initial_balance), float(initial_balance), float(initial_balance), now),
        )
        conn.commit()


# ✅ Get recent price series
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


# ✅ Get recent Open Interest series (for trend detection)
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


# ✅ Get last price (for dedup in engine)
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
