class EventRouter:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    async def _handle_best_bid_ask_event(self, data):
        bid = float(data.get("best_bid", 0))
        ask = float(data.get("best_ask", 0))
        mid = (bid + ask) / 2
        spread = (ask - bid) if mid > 0 else 0
        self.pipeline.record_ws_tick(
            data.get("asset_id"),
            "best_bid_ask",
            best_bid=bid,
            best_ask=ask,
            mid=mid,
            spread=spread,
        )
        await self.pipeline.process_price_update(data.get("asset_id"), mid, spread)

    async def _handle_price_change_event(self, data):
        for price_change in data.get("price_changes", []):
            bid = float(price_change.get("best_bid") or 0)
            ask = float(price_change.get("best_ask") or 0)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread = ask - bid
                self.pipeline.record_ws_tick(
                    price_change.get("asset_id"),
                    "price_change",
                    best_bid=bid,
                    best_ask=ask,
                    mid=mid,
                    spread=spread,
                )
                await self.pipeline.process_price_update(
                    price_change.get("asset_id"), mid, spread
                )

    async def _handle_book_event(self, data):
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not (bids and asks):
            return

        bid_price = float(bids[0].get("price", 0))
        ask_price = float(asks[0].get("price", 0))
        if bid_price <= 0 or ask_price <= 0 or ask_price < bid_price:
            return
        mid = (bid_price + ask_price) / 2
        spread = ask_price - bid_price
        if spread > 0.30:
            return

        top_bids = bids[:5]
        top_asks = asks[:5]
        total_bid_vol = sum([float(b.get("size", 0)) for b in top_bids])
        total_ask_vol = sum([float(a.get("size", 0)) for a in top_asks])
        total_volume = total_bid_vol + total_ask_vol
        deep_pressure = (
            (total_bid_vol - total_ask_vol) / total_volume if total_volume > 0 else 0
        )
        self.pipeline.record_ws_tick(
            data.get("asset_id"),
            "book",
            best_bid=bid_price,
            best_ask=ask_price,
            mid=mid,
            spread=spread,
            bid_sz_top5=total_bid_vol,
            ask_sz_top5=total_ask_vol,
            depth_top5=total_volume,
            pressure=deep_pressure,
        )
        await self.pipeline.process_price_update(
            data.get("asset_id"), mid, spread, deep_pressure, total_volume
        )

    async def _handle_last_trade_event(self, data):
        last_price = float(data.get("price") or 0)
        self.pipeline.record_ws_tick(
            data.get("asset_id"),
            "last_trade_price",
            last_trade_price=last_price,
        )
        await self.pipeline.process_price_update(data.get("asset_id"), last_price)

    async def on_ws_event(self, data):
        event_type = data.get("event_type")
        if event_type == "best_bid_ask":
            await self._handle_best_bid_ask_event(data)
        elif event_type == "price_change":
            await self._handle_price_change_event(data)
        elif event_type == "book":
            await self._handle_book_event(data)
        elif event_type == "last_trade_price":
            await self._handle_last_trade_event(data)
