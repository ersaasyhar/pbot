import os
import sqlite3
import time

from app.logger import get_logger
from data.db_config import DB_PATH


def init_db_schema():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000")

    c.execute(
        """
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
        """
    )
    try:
        c.execute("ALTER TABLE market_prices ADD COLUMN end_time INTEGER")
    except Exception as e:
        get_logger().debug(f"storage: market_prices end_time column add skipped: {e}")

    c.execute(
        """
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
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_ws_ticks_ts ON ws_ticks(ts_ms)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_ws_ticks_token_ts ON ws_ticks(token_id, ts_ms)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_ws_ticks_coin_tf_ts ON ws_ticks(coin, timeframe, ts_ms)"
    )

    c.execute(
        """
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
        """
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_trades_status_entry ON paper_trades(status, entry_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_trades_coin_tf ON paper_trades(coin, timeframe)"
    )
    try:
        c.execute("ALTER TABLE paper_trades ADD COLUMN end_time INTEGER")
    except Exception as e:
        get_logger().debug(f"storage: paper_trades end_time column add skipped: {e}")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_portfolio_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            initial_balance REAL NOT NULL,
            balance REAL NOT NULL,
            high_water_mark REAL NOT NULL,
            updated_ts INTEGER NOT NULL
        )
        """
    )
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
