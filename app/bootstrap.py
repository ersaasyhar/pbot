from dotenv import load_dotenv

from data.storage import init_db


def bootstrap_runtime(init_database=True):
    """
    Shared startup for all local commands:
    - load .env values
    - ensure SQLite schema exists
    """
    load_dotenv()
    if init_database:
        init_db()
