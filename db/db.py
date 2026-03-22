import sqlite3


class Database:
    def __init__(self, path="markets.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_table()

    def create_table(self):
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS market_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT,
            question TEXT,
            price REAL,
            volume REAL,
            timestamp INTEGER
        )
        """)
        self.conn.commit()

    # ✅ Get last price for deduplication
    def get_last_price(self, market_id):
        cur = self.conn.execute(
            """
            SELECT price FROM market_prices
            WHERE market_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """,
            (market_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    # ✅ Insert new price row
    def insert_price(self, market):
        self.conn.execute(
            """
            INSERT INTO market_prices (market_id, question, price, volume, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                market["market_id"],
                market["question"],
                market["price"],
                market["volume"],
                market["timestamp"],
            ),
        )
        self.conn.commit()

    # ✅ THIS is the block you asked about
    def save_price(self, market):
        last = self.get_last_price(market["market_id"])

        # 🚫 Skip duplicate price (no movement)
        if last and abs(last["price"] - market["price"]) < 1e-6:
            return False

        self.insert_price(market)
        return True
