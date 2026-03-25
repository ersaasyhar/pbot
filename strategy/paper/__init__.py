from strategy.paper.execution_manager import execute_virtual_trade
from strategy.paper.exit_manager import update_paper_trades
from strategy.paper.risk_manager import calculate_stake
from strategy.paper.state import load_portfolio

__all__ = [
    "load_portfolio",
    "calculate_stake",
    "execute_virtual_trade",
    "update_paper_trades",
]
