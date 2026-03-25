from strategy.paper.storage_adapter import load_portfolio_snapshot


def load_portfolio():
    return load_portfolio_snapshot(history_limit=5000)
