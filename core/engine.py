import asyncio
import sqlite3

from app.bootstrap import bootstrap_runtime
from app.config import (
    BOT_CONFIG,
    RISK_PROFILES,
    SELECTED_RISK_PROFILE_NAME,
    SELECTED_SIZING_PROFILE_NAME,
)
from app.logger import get_logger
from core.market_registry import upsert_active_markets
from core.runtime_state import RuntimeState
from core.services.event_router import EventRouter
from core.services.external_context_service import ExternalContextService
from core.services.sync_coordinator import SyncCoordinator
from core.services.trading_pipeline import TradingPipeline
from data.fetcher import fetch_markets_async
from data.storage import DB_PATH

logger = get_logger()

RISK_PROFILE_NAME = SELECTED_RISK_PROFILE_NAME
SELECTED_RISK_PROFILE = RISK_PROFILES.get(RISK_PROFILE_NAME)
SIZING_PROFILE_NAME = SELECTED_SIZING_PROFILE_NAME

RUNTIME = RuntimeState()


async def run():
    bootstrap_runtime(init_database=True)
    logger.info(
        "🚀 v40 (sqlite portfolio source-of-truth + replay recorder + deadlock guard) "
        f"| Risk: {RISK_PROFILE_NAME} | Size: {SIZING_PROFILE_NAME}"
    )

    if RUNTIME.conn is not None:
        try:
            RUNTIME.conn.close()
        except Exception:
            pass

    RUNTIME.reset_runtime()
    RUNTIME.conn = sqlite3.connect(
        DB_PATH, check_same_thread=False, timeout=30, isolation_level=None
    )
    RUNTIME.conn.execute("PRAGMA journal_mode=WAL")
    RUNTIME.conn.execute("PRAGMA synchronous=NORMAL")
    RUNTIME.conn.execute("PRAGMA busy_timeout=5000")

    pipeline = TradingPipeline(
        runtime=RUNTIME,
        logger=logger,
        selected_risk_profile=SELECTED_RISK_PROFILE,
        sizing_profile_name=SIZING_PROFILE_NAME,
    )
    event_router = EventRouter(pipeline=pipeline)
    external_context_service = ExternalContextService(
        runtime=RUNTIME,
        logger=logger,
        bot_config=BOT_CONFIG,
    )
    sync_coordinator = SyncCoordinator(
        runtime=RUNTIME,
        logger=logger,
        selected_risk_profile=SELECTED_RISK_PROFILE,
        pipeline=pipeline,
    )

    initial_markets = await fetch_markets_async()
    upsert_active_markets(RUNTIME, initial_markets)
    initial_tokens = list(RUNTIME.active_markets.keys())
    logger.info(f"Loaded {len(initial_tokens)} markets for initial WS subscription.")

    asyncio.create_task(sync_coordinator.sync_loop())
    asyncio.create_task(external_context_service.run())
    await RUNTIME.ws_client.connect_and_listen(initial_tokens, event_router.on_ws_event)


if __name__ == "__main__":
    asyncio.run(run())
