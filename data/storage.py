import sqlite3
import os

DB_PATH = "db/market_v5.db"

def init_db():
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

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
        timestamp INTEGER
    )
    """)

    conn.commit()
    conn.close()

# ✅ Insert full market snapshot
def insert_market(conn, market):
    # We use the existing connection passed from the engine
    conn.execute("""
        INSERT INTO market_prices (market_id, condition_id, clob_token_id, question, price, volume, open_interest, coin, timeframe, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        market.get("market_id"),
        market.get("condition_id"),
        market.get("clob_token_id"),
        market.get("question"),
        market.get("price"),
        market.get("volume"),
        market.get("open_interest", 0.0),
        market.get("coin"),
        market.get("timeframe"),
        market.get("timestamp")
    ))

# ✅ Get recent price series
def get_recent_prices(conn, market_id, limit=20):
    cur = conn.execute("""
        SELECT price FROM market_prices
        WHERE market_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (market_id, limit))

    rows = cur.fetchall()
    return [float(r[0]) for r in reversed(rows)]

# ✅ Get recent Open Interest series (for trend detection)
def get_recent_oi(conn, market_id, limit=10):
    cur = conn.execute("""
        SELECT open_interest FROM market_prices
        WHERE market_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (market_id, limit))

    rows = cur.fetchall()
    return [float(r[0]) for r in reversed(rows)]

# ✅ Get last price (for dedup in engine)
def get_last_price(conn, market_id):
    cur = conn.execute("""
        SELECT price, volume FROM market_prices
        WHERE market_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
    """, (market_id,))
    
    row = cur.fetchone()
    if not row:
        return None
        
    return {
        "price": float(row[0]),
        "volume": float(row[1])
    }
