"""
Compatibility facade for paper-trading operations.
New code lives under strategy/paper/* modules.
"""

from strategy.paper.execution_manager import execute_virtual_trade
from strategy.paper.exit_manager import resolve_stale_exit as _resolve_stale_exit
from strategy.paper.exit_manager import update_paper_trades
from strategy.paper.risk_manager import calculate_stake
from strategy.paper.risk_manager import (
    risk_profile_for_timeframe as _risk_profile_for_timeframe,
)
from strategy.paper.state import load_portfolio

__all__ = [
    "load_portfolio",
    "calculate_stake",
    "execute_virtual_trade",
    "update_paper_trades",
    "_risk_profile_for_timeframe",
    "_resolve_stale_exit",
]
