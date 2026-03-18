import sqlite3
import os

DB_PATH = "db/market_v5.db"

def init_db():
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Updated schema with coin and timeframe metadata
    c.execute("""
    CREATE TABLE IF NOT EXISTS market_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id TEXT,
        question TEXT,
        price REAL,
        volume REAL,
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
        INSERT INTO market_prices (market_id, question, price, volume, coin, timeframe, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        market["market_id"],
        market["question"],
        market["price"],
        market["volume"],
        market.get("coin"),
        market["timeframe"],
        market["timestamp"]
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
    return [r[0] for r in reversed(rows)]

# ✅ Get last price (for dedup in engine)
def get_last_price(conn, market_id):
    cur = conn.execute("""
        SELECT price FROM market_prices
        WHERE market_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
    """, (market_id,))
    
    # Return as a dict-like Row for engine compatibility
    return cur.fetchone()
