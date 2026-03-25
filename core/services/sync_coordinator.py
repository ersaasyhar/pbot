import asyncio

from core.market_registry import upsert_active_markets
from core.strategy_utils import compute_coin_gate
from data.fetcher import fetch_markets_async
from data.storage import get_recent_closed_trades
from strategy.paper_trader import update_paper_trades


class SyncCoordinator:
    def __init__(self, runtime, logger, selected_risk_profile, pipeline):
        self.runtime = runtime
        self.logger = logger
        self.selected_risk_profile = selected_risk_profile
        self.pipeline = pipeline

    def _update_allowlists(self):
        profile = self.selected_risk_profile or {}
        self.runtime.allowed_entry_coins = set(
            [str(c).lower() for c in profile.get("trade_allowed_coins", [])]
        )
        self.runtime.allowed_entry_timeframes = set(
            [str(tf) for tf in profile.get("trade_allowed_timeframes", [])]
        )

    def _refresh_coin_gate(self):
        profile = self.selected_risk_profile or {}
        history = get_recent_closed_trades(limit=5000)
        blocked_map, coin_stats = compute_coin_gate(profile, history)
        new_blocked = set(blocked_map.keys())
        if new_blocked != self.runtime.blocked_coins:
            self.runtime.blocked_coins = new_blocked
            self.runtime.blocked_coin_stats = coin_stats
            if self.runtime.blocked_coins:
                self.logger.info(
                    f"🧱 COIN GATE active: {sorted(self.runtime.blocked_coins)} | details={blocked_map}"
                )
            else:
                self.logger.info("🧱 COIN GATE active: none")

        if self.runtime.allowed_entry_coins:
            self.logger.info(
                f"🧭 ENTRY COINS allowlist: {sorted(self.runtime.allowed_entry_coins)}"
            )
        if self.runtime.allowed_entry_timeframes:
            self.logger.info(
                "🧭 ENTRY TIMEFRAMES allowlist: "
                f"{sorted(self.runtime.allowed_entry_timeframes)}"
            )

    async def _refresh_markets_and_subscriptions(self):
        markets = await fetch_markets_async()
        new_tokens = upsert_active_markets(self.runtime, markets)
        if new_tokens:
            await self.runtime.ws_client.update_subscription(new_tokens)

    async def sync_loop(self):
        while True:
            try:
                self._update_allowlists()
                self._refresh_coin_gate()
                await self._refresh_markets_and_subscriptions()

                self.pipeline.execute_top_candidates()
                update_paper_trades(
                    self.runtime.latest_prices,
                    self.runtime.latest_analysis,
                )
                self.pipeline.flush_ws_tick_buffer(force=True)
                self.logger.info(
                    f"📈 STREAM HEALTH: {self.runtime.updates_count} updates last cycle."
                )
                self.runtime.updates_count = 0
            except Exception as exc:
                self.logger.error(f"Sync Loop Error: {exc}")
            await asyncio.sleep(60)
