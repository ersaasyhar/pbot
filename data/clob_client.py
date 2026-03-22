import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

load_dotenv()


def get_clob_client():
    host = "https://clob.polymarket.com"
    key = os.getenv("POLYMARKET_API_KEY")
    secret = os.getenv("POLYMARKET_API_SECRET")
    passphrase = os.getenv("POLYMARKET_API_PASSPHRASE")
    private_key = os.getenv("POLYMARKET_PK")

    # Create ApiCreds object
    creds = ApiCreds(api_key=key, api_secret=secret, api_passphrase=passphrase)

    client = ClobClient(host, key=private_key, chain_id=POLYGON, creds=creds)
    return client


def get_market_spread(client, token_id):
    """
    Fetches the orderbook and calculates spread for a specific token_id.
    """
    try:
        # The correct method is get_order_book
        orderbook = client.get_order_book(token_id)

        # In current version, get_order_book likely returns an object or dict
        if hasattr(orderbook, "bids"):
            bids = orderbook.bids
            asks = orderbook.asks
        else:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

        if not bids or not asks:
            return None

        def get_val(item, key):
            if isinstance(item, dict):
                return item.get(key)
            return getattr(item, key)

        best_bid = float(get_val(bids[0], "price"))
        best_ask = float(get_val(asks[0], "price"))
        spread = best_ask - best_bid
        midpoint = (best_ask + best_bid) / 2

        return {
            "bid": best_bid,
            "ask": best_ask,
            "spread": spread,
            "midpoint": midpoint,
        }
    except Exception:
        # print(f"Error fetching spread for {token_id}: {e}")
        return None
