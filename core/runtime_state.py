from dataclasses import dataclass, field

from data.websocket_client import PolymarketWS


@dataclass
class RuntimeState:
    active_markets: dict = field(default_factory=dict)
    active_market_by_key: dict = field(default_factory=dict)
    subscribed_tokens: set = field(default_factory=set)
    latest_prices: dict = field(default_factory=dict)
    latest_spreads: dict = field(default_factory=dict)
    latest_pressure: dict = field(default_factory=dict)
    latest_depth: dict = field(default_factory=dict)
    latest_analysis: dict = field(default_factory=dict)
    latest_tf_signals: dict = field(default_factory=dict)
    latest_external_spot: dict = field(default_factory=dict)
    latest_perp_context: dict = field(default_factory=dict)
    signal_state: dict = field(default_factory=dict)
    entry_candidates: dict = field(default_factory=dict)
    blocked_coins: set = field(default_factory=set)
    blocked_coin_stats: dict = field(default_factory=dict)
    allowed_entry_coins: set = field(default_factory=set)
    allowed_entry_timeframes: set = field(default_factory=set)
    last_saved_price: dict = field(default_factory=dict)
    ws_tick_buffer: list = field(default_factory=list)
    ws_tick_flush_size: int = 250
    updates_count: int = 0
    conn: object | None = None
    ws_client: PolymarketWS = field(default_factory=PolymarketWS)

    def reset_runtime(self) -> None:
        self.active_markets.clear()
        self.active_market_by_key.clear()
        self.subscribed_tokens.clear()
        self.latest_prices.clear()
        self.latest_spreads.clear()
        self.latest_pressure.clear()
        self.latest_depth.clear()
        self.latest_analysis.clear()
        self.latest_tf_signals.clear()
        self.latest_external_spot.clear()
        self.latest_perp_context.clear()
        self.signal_state.clear()
        self.entry_candidates.clear()
        self.blocked_coins.clear()
        self.blocked_coin_stats.clear()
        self.allowed_entry_coins.clear()
        self.allowed_entry_timeframes.clear()
        self.last_saved_price.clear()
        self.ws_tick_buffer.clear()
        self.updates_count = 0
