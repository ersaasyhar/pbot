import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from app.logger import get_logger

load_dotenv()
logger = get_logger()


def _env_first(*names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def get_clob_runtime_config():
    funder = _env_first("POLYMARKET_FUNDER_ADDRESS", "MY_FUNDER")
    signature_type_raw = _env_first("POLYMARKET_SIGNATURE_TYPE")
    signature_type = (
        int(signature_type_raw)
        if signature_type_raw is not None
        else (2 if funder else 0)
    )
    return {
        "host": "https://clob.polymarket.com",
        "private_key": _env_first("POLYMARKET_PK", "MY_PRIVATE_KEY"),
        "api_key": os.getenv("POLYMARKET_API_KEY"),
        "api_secret": os.getenv("POLYMARKET_API_SECRET"),
        "api_passphrase": os.getenv("POLYMARKET_API_PASSPHRASE"),
        "funder": funder,
        "signature_type": signature_type,
    }


def get_clob_client():
    cfg = get_clob_runtime_config()
    private_key = cfg["private_key"]
    if not private_key:
        raise RuntimeError(
            "Missing private key. Set `POLYMARKET_PK` (or `MY_PRIVATE_KEY`)."
        )

    creds = None
    if cfg["api_key"] and cfg["api_secret"] and cfg["api_passphrase"]:
        creds = ApiCreds(
            api_key=cfg["api_key"],
            api_secret=cfg["api_secret"],
            api_passphrase=cfg["api_passphrase"],
        )

    client = ClobClient(
        cfg["host"],
        key=private_key,
        chain_id=POLYGON,
        creds=creds,
        signature_type=cfg["signature_type"],
        funder=cfg["funder"],
    )

    # If API creds are not supplied, derive/create them from signer+funder context.
    if creds is None:
        derived = client.create_or_derive_api_creds()
        client.set_api_creds(derived)
        logger.info("CLOB API creds derived at runtime from signer/funder context.")

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
    except Exception as e:
        logger.debug(f"Error fetching spread for {token_id}: {e}")
        return None
