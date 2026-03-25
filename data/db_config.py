import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.getenv("PBOT_DB_PATH", os.path.join(BASE_DIR, "db", "market_v5.db"))
