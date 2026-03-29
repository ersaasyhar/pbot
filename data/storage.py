from data.db_config import BASE_DIR, DB_PATH
from data.repositories.market_repository import (
    get_latest_external_spot,
    get_latest_perp_context,
    get_last_price,
    get_market_end_time,
    get_recent_oi,
    get_recent_prices,
    get_yes_price_at_close,
    insert_external_spot_tick,
    insert_market,
    insert_perp_context_tick,
    insert_ws_ticks_bulk,
)
from data.repositories.migration_repository import migrate_legacy_json_portfolio
from data.repositories.portfolio_repository import (
    adjust_portfolio_balance,
    close_paper_trade,
    get_recent_closed_trades,
    load_paper_portfolio_snapshot,
    reset_paper_trading_state,
    upsert_paper_trade_entry,
)
from data.repositories.schema_repository import init_db_schema


def init_db():
    init_db_schema()
    migrate_legacy_json_portfolio()


__all__ = [
    "BASE_DIR",
    "DB_PATH",
    "init_db",
    "insert_market",
    "insert_ws_ticks_bulk",
    "insert_external_spot_tick",
    "insert_perp_context_tick",
    "load_paper_portfolio_snapshot",
    "get_recent_closed_trades",
    "adjust_portfolio_balance",
    "upsert_paper_trade_entry",
    "close_paper_trade",
    "get_market_end_time",
    "get_yes_price_at_close",
    "migrate_legacy_json_portfolio",
    "reset_paper_trading_state",
    "get_recent_prices",
    "get_recent_oi",
    "get_last_price",
    "get_latest_external_spot",
    "get_latest_perp_context",
]
