import asyncio
from app.bootstrap import bootstrap_runtime
from core.engine import run

if __name__ == "__main__":
    bootstrap_runtime(init_database=True)
    asyncio.run(run())
