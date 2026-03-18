from data.storage import init_db
from core.engine import run

if __name__ == "__main__":
    init_db()
    run()