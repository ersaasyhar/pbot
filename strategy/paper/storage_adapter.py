from data.storage import (
    adjust_portfolio_balance,
    close_paper_trade,
    get_market_end_time,
    get_yes_price_at_close,
    load_paper_portfolio_snapshot,
    upsert_paper_trade_entry,
)


def load_portfolio_snapshot(history_limit=5000):
    return load_paper_portfolio_snapshot(history_limit=history_limit)


__all__ = [
    "load_portfolio_snapshot",
    "adjust_portfolio_balance",
    "close_paper_trade",
    "get_market_end_time",
    "get_yes_price_at_close",
    "upsert_paper_trade_entry",
]
