import json
import asyncio
import websockets
from app.logger import get_logger

logger = get_logger()

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class PolymarketWS:
    def __init__(self):
        self.uri = WS_URL
        self.ws = None
        self.callback = None
        self.initial_tokens = []

    async def connect_and_listen(self, initial_tokens, callback):
        """
        Connects and immediately subscribes to avoid server-side timeout.
        """
        self.initial_tokens = initial_tokens
        self.callback = callback
        headers = {"User-Agent": "Mozilla/5.0"}

        while True:
            try:
                logger.info(f"Connecting to WS: {self.uri}")
                async with websockets.connect(
                    self.uri, additional_headers=headers, ping_interval=None
                ) as ws:
                    self.ws = ws

                    # 1. IMMEDIATE SUBSCRIPTION (Rule #1 in docs)
                    sub_msg = {
                        "type": "market",
                        "assets_ids": [str(t) for t in self.initial_tokens],
                        "custom_feature_enabled": True,
                    }
                    await self.ws.send(json.dumps(sub_msg))
                    logger.info(
                        f"WS: Immediate subscription sent for {len(self.initial_tokens)} tokens."
                    )

                    # 2. START HEARTBEAT (Rule #2 in docs)
                    heartbeat_task = asyncio.create_task(self.heartbeat_loop())

                    # 3. LISTEN LOOP
                    while True:
                        message = await self.ws.recv()
                        if message == "PONG":
                            continue

                        try:
                            data = json.loads(message)
                            if data.get("type") == "subscription_success":
                                continue

                            events = data if isinstance(data, list) else [data]
                            for ev in events:
                                if isinstance(ev, dict):
                                    await self.callback(ev)
                        except:
                            continue

            except Exception as e:
                logger.warning(f"WS Connection Error: {e}. Reconnecting in 5s...")
                self.ws = None
                await asyncio.sleep(5)

    async def heartbeat_loop(self):
        while self.ws:
            try:
                await self.ws.send("PING")
                await asyncio.sleep(10)
            except:
                break

    async def update_subscription(self, new_tokens):
        """
        Uses the 'Dynamic Subscription' feature from the docs
        """
        if self.ws:
            msg = {
                "operation": "subscribe",
                "assets_ids": [str(t) for t in new_tokens],
                "type": "market",  # Some versions require type even on update
                "custom_feature_enabled": True,
            }
            await self.ws.send(json.dumps(msg))
            logger.info(f"WS: Dynamically subscribed to {len(new_tokens)} new tokens.")
