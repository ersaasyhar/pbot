import asyncio
import json
import random
import time
from collections import deque

import aiohttp
import websockets

from data.storage import insert_external_spot_tick, insert_perp_context_tick


class ExternalContextService:
    def __init__(self, runtime, logger, bot_config):
        self.runtime = runtime
        self.logger = logger

        self.enabled = bool(bot_config.get("external_context_enabled", True))

        self.spot_symbol = str(
            bot_config.get("external_spot_symbol", "btcusdt")
        ).lower()
        self.perp_symbol = str(
            bot_config.get("external_perp_symbol", "BTCUSDT")
        ).upper()

        self.perp_poll_sec = max(10, int(bot_config.get("perp_poll_interval_sec", 15)))

        self._spot_mid_window = deque()
        self._oi_window = deque()
        self._liq_events = deque()

    @staticmethod
    def _next_backoff(attempt, base=2.0, cap=60.0):
        exp = min(cap, base * (2 ** max(0, attempt - 1)))
        jitter = random.uniform(0.0, 1.5)
        return exp + jitter

    def _prune(self):
        now = time.time()

        while self._spot_mid_window and (now - self._spot_mid_window[0][0]) > 10:
            self._spot_mid_window.popleft()

        while self._oi_window and (now - self._oi_window[0][0]) > 120:
            self._oi_window.popleft()

        while self._liq_events and (now - self._liq_events[0][0]) > 90:
            self._liq_events.popleft()

    def _liq_1m(self):
        self._prune()

        now = time.time()
        long_usd = 0.0
        short_usd = 0.0

        for ts, side, usd in self._liq_events:
            if (now - ts) > 60:
                continue

            if side == "SELL":
                long_usd += usd
            elif side == "BUY":
                short_usd += usd

        return long_usd, short_usd

    async def _spot_ws_loop(self):
        uri = f"wss://stream.binance.com:9443/ws/{self.spot_symbol}@bookTicker"
        attempt = 0

        while True:
            try:
                async with websockets.connect(
                    uri,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_queue=1000,
                    open_timeout=30,
                ) as ws:
                    attempt = 0
                    self.logger.info(
                        f"external_context: connected spot ws {self.spot_symbol}"
                    )

                    async for msg in ws:
                        try:
                            data = json.loads(msg)

                            bid = float(data.get("b", 0) or 0)
                            ask = float(data.get("a", 0) or 0)
                            bid_sz = float(data.get("B", 0) or 0)
                            ask_sz = float(data.get("A", 0) or 0)

                            if bid <= 0 or ask <= 0:
                                continue

                            mid = (bid + ask) / 2
                            spread = ask - bid

                            spread_bps = (spread / mid) * 10000 if mid > 0 else None

                            denom = max(1e-9, bid_sz + ask_sz)
                            imbalance = (bid_sz - ask_sz) / denom

                            now_ts = time.time()

                            self._spot_mid_window.append((now_ts, mid))
                            self._prune()

                            momentum_10s = 0.0

                            if self._spot_mid_window:
                                base_mid = self._spot_mid_window[0][1]
                                if base_mid > 0:
                                    momentum_10s = (mid - base_mid) / base_mid

                            row = {
                                "ts_ms": int(now_ts * 1000),
                                "venue": "binance_spot",
                                "symbol": self.spot_symbol.upper(),
                                "bid": bid,
                                "ask": ask,
                                "mid": mid,
                                "spread": spread,
                                "spread_bps": spread_bps,
                                "bid_size": bid_sz,
                                "ask_size": ask_sz,
                                "imbalance": imbalance,
                                "momentum_10s": momentum_10s,
                            }

                            self.runtime.latest_external_spot = row

                            if self.runtime.conn is not None:
                                insert_external_spot_tick(self.runtime.conn, row)

                        except Exception as exc:
                            self.logger.debug(
                                f"external_context: spot ws parse error: {exc}"
                            )

            except Exception as exc:
                attempt += 1
                wait_s = self._next_backoff(attempt)

                self.logger.warning(
                    f"external_context: spot ws reconnect after error: {exc} | backoff={wait_s:.1f}s"
                )

                await asyncio.sleep(wait_s)

    async def _liq_force_order_loop(self):
        uri = f"wss://fstream.binance.com/ws/{self.perp_symbol.lower()}@forceOrder"
        attempt = 0

        while True:
            try:
                async with websockets.connect(
                    uri,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_queue=1000,
                    open_timeout=30,
                ) as ws:
                    attempt = 0
                    self.logger.info("external_context: connected liquidation stream")

                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            order = data.get("o", {})

                            side = str(order.get("S", ""))
                            ap = float(order.get("ap", 0) or 0)
                            qty = float(order.get("q", 0) or 0)

                            usd = ap * qty

                            if side in {"BUY", "SELL"} and usd > 0:
                                self._liq_events.append((time.time(), side, usd))
                                self._prune()

                        except Exception:
                            continue

            except Exception as exc:
                attempt += 1
                wait_s = self._next_backoff(attempt)

                self.logger.warning(
                    f"external_context: liquidation ws reconnect after error: {exc} | backoff={wait_s:.1f}s"
                )

                await asyncio.sleep(wait_s)

    async def _perp_poll_loop(self):
        premium_url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        oi_url = "https://fapi.binance.com/fapi/v1/openInterest"

        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(
                        premium_url,
                        params={"symbol": self.perp_symbol},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as r1:
                        p_data = await r1.json() if r1.status == 200 else {}

                    async with session.get(
                        oi_url,
                        params={"symbol": self.perp_symbol},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as r2:
                        oi_data = await r2.json() if r2.status == 200 else {}

                    funding_rate = float(p_data.get("lastFundingRate", 0) or 0)
                    mark_price = float(p_data.get("markPrice", 0) or 0)
                    oi_now = float(oi_data.get("openInterest", 0) or 0)

                    now_ts = time.time()

                    self._oi_window.append((now_ts, oi_now))
                    self._prune()

                    oi_delta_1m = 0.0
                    if self._oi_window:
                        oi_delta_1m = oi_now - float(self._oi_window[0][1])

                    liq_long_1m, liq_short_1m = self._liq_1m()

                    spot_mid = float(
                        (self.runtime.latest_external_spot or {}).get("mid") or 0
                    )

                    basis_bps = 0.0
                    if mark_price > 0 and spot_mid > 0:
                        basis_bps = ((mark_price - spot_mid) / spot_mid) * 10000

                    row = {
                        "ts_ms": int(now_ts * 1000),
                        "venue": "binance_futures",
                        "symbol": self.perp_symbol,
                        "funding_rate": funding_rate,
                        "open_interest": oi_now,
                        "oi_delta_1m": oi_delta_1m,
                        "liq_long_1m": liq_long_1m,
                        "liq_short_1m": liq_short_1m,
                        "basis_bps": basis_bps,
                    }

                    self.runtime.latest_perp_context = row

                    if self.runtime.conn is not None:
                        insert_perp_context_tick(self.runtime.conn, row)

                except Exception as exc:
                    self.logger.debug(f"external_context: perp poll error: {exc}")

                await asyncio.sleep(max(2, self.perp_poll_sec))

    async def run(self):
        if not self.enabled:
            self.logger.info("external_context: disabled")
            return

        await asyncio.sleep(1)

        await asyncio.gather(
            self._spot_ws_loop(),
            self._liq_force_order_loop(),
            self._perp_poll_loop(),
        )
