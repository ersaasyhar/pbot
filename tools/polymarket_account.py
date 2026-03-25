import argparse
import json
from typing import Any
import requests

from data.clob_client import get_clob_client, get_clob_runtime_config
from py_clob_client.clob_types import (
    AssetType,
    BalanceAllowanceParams,
    MarketOrderArgs,
    OpenOrderParams,
    OrderArgs,
    TradeParams,
)


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
        return to_jsonable(obj.dict())
    if hasattr(obj, "__dict__"):
        return to_jsonable(vars(obj))
    return str(obj)


def print_json(obj: Any) -> None:
    print(json.dumps(to_jsonable(obj), indent=2, sort_keys=True))


def cmd_whoami(args: argparse.Namespace) -> None:
    client = get_clob_client()
    cfg = get_clob_runtime_config()
    print_json(
        {
            "signer_address": client.get_address(),
            "funder_address": cfg.get("funder"),
            "signature_type": cfg.get("signature_type"),
        }
    )


def cmd_balance(args: argparse.Namespace) -> None:
    client = get_clob_client()
    asset_type = (
        AssetType.COLLATERAL
        if args.asset_type.lower() == "collateral"
        else AssetType.CONDITIONAL
    )
    params = BalanceAllowanceParams(
        asset_type=asset_type,
        token_id=args.token_id,
        signature_type=args.signature_type,
    )
    data = to_jsonable(client.get_balance_allowance(params))
    if asset_type == AssetType.COLLATERAL:
        raw_balance = str(data.get("balance", "0"))
        try:
            usdc_balance = int(raw_balance) / 1_000_000
            data["usdc_balance"] = f"{usdc_balance:.6f}"
        except Exception:
            pass
    print_json(data)


def cmd_trades(args: argparse.Namespace) -> None:
    client = get_clob_client()
    cfg = get_clob_runtime_config()
    maker = args.maker_address or cfg.get("funder") or client.get_address()
    params = TradeParams(
        maker_address=maker,
        market=args.market,
        asset_id=args.asset_id,
        before=args.before,
        after=args.after,
    )
    print_json(client.get_trades(params, next_cursor=args.next_cursor))


def cmd_orders(args: argparse.Namespace) -> None:
    client = get_clob_client()
    params = OpenOrderParams(
        id=args.order_id,
        market=args.market,
        asset_id=args.asset_id,
    )
    print_json(client.get_orders(params, next_cursor=args.next_cursor))


def cmd_public_trades(args: argparse.Namespace) -> None:
    cfg = get_clob_runtime_config()
    user = args.user or cfg.get("funder")
    if not user:
        raise SystemExit(
            "No user address found. Set POLYMARKET_FUNDER_ADDRESS or pass --user."
        )
    url = "https://data-api.polymarket.com/trades"
    resp = requests.get(url, params={"user": user, "limit": args.limit}, timeout=20)
    resp.raise_for_status()
    print_json(resp.json())


def cmd_activity(args: argparse.Namespace) -> None:
    cfg = get_clob_runtime_config()
    user = args.user or cfg.get("funder")
    if not user:
        raise SystemExit(
            "No user address found. Set POLYMARKET_FUNDER_ADDRESS or pass --user."
        )
    url = "https://data-api.polymarket.com/activity"
    resp = requests.get(url, params={"user": user, "limit": args.limit}, timeout=20)
    resp.raise_for_status()
    print_json(resp.json())


def cmd_place_limit(args: argparse.Namespace) -> None:
    client = get_clob_client()
    side = args.side.upper()
    order_args = OrderArgs(
        token_id=args.token_id,
        price=args.price,
        size=args.size,
        side=side,
    )
    signed = client.create_order(order_args)
    if not args.post:
        print("Dry run only. Signed limit order (not posted):")
        print_json(signed)
        print("Use --post to send this order to Polymarket.")
        return
    if not args.confirm:
        raise SystemExit("Refusing to post without --confirm.")
    resp = client.post_order(signed, orderType=args.order_type)
    print_json(resp)


def cmd_place_market(args: argparse.Namespace) -> None:
    client = get_clob_client()
    side = args.side.upper()
    order_args = MarketOrderArgs(
        token_id=args.token_id,
        amount=args.amount,
        side=side,
    )
    signed = client.create_market_order(order_args)
    if not args.post:
        print("Dry run only. Signed market order (not posted):")
        print_json(signed)
        print("Use --post to send this order to Polymarket.")
        return
    if not args.confirm:
        raise SystemExit("Refusing to post without --confirm.")
    resp = client.post_order(signed, orderType=args.order_type)
    print_json(resp)


def cmd_cancel(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise SystemExit("Refusing to cancel without --confirm.")
    client = get_clob_client()
    if len(args.order_ids) == 1:
        print_json(client.cancel(args.order_ids[0]))
    else:
        print_json(client.cancel_orders(args.order_ids))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Polymarket account utilities (balance, history, orders)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    whoami = sub.add_parser("whoami", help="Show resolved wallet address")
    whoami.set_defaults(func=cmd_whoami)

    bal = sub.add_parser(
        "balance", help="Get collateral/conditional balance + allowance"
    )
    bal.add_argument(
        "--asset-type",
        default="collateral",
        choices=["collateral", "conditional"],
    )
    bal.add_argument(
        "--token-id", default=None, help="Required for conditional balance"
    )
    bal.add_argument("--signature-type", type=int, default=-1)
    bal.set_defaults(func=cmd_balance)

    trades = sub.add_parser("trades", help="Get trade history")
    trades.add_argument("--maker-address", default=None)
    trades.add_argument("--market", default=None)
    trades.add_argument("--asset-id", default=None)
    trades.add_argument("--before", type=int, default=None)
    trades.add_argument("--after", type=int, default=None)
    trades.add_argument("--next-cursor", default="MA==")
    trades.set_defaults(func=cmd_trades)

    orders = sub.add_parser("orders", help="Get open orders")
    orders.add_argument("--order-id", default=None)
    orders.add_argument("--market", default=None)
    orders.add_argument("--asset-id", default=None)
    orders.add_argument("--next-cursor", default="MA==")
    orders.set_defaults(func=cmd_orders)

    public_trades = sub.add_parser(
        "public-trades",
        help="Get user trades from Data API (address-based, includes proxy wallet activity)",
    )
    public_trades.add_argument("--user", default=None)
    public_trades.add_argument("--limit", type=int, default=50)
    public_trades.set_defaults(func=cmd_public_trades)

    activity = sub.add_parser(
        "activity",
        help="Get user activity feed from Data API (deposits/trades/redeems)",
    )
    activity.add_argument("--user", default=None)
    activity.add_argument("--limit", type=int, default=50)
    activity.set_defaults(func=cmd_activity)

    pl = sub.add_parser("place-limit", help="Create/post limit order")
    pl.add_argument("--token-id", required=True)
    pl.add_argument("--price", type=float, required=True)
    pl.add_argument("--size", type=float, required=True)
    pl.add_argument("--side", choices=["BUY", "SELL"], required=True)
    pl.add_argument("--order-type", default="GTC", choices=["GTC", "FOK", "GTD"])
    pl.add_argument("--post", action="store_true", help="Post order to exchange")
    pl.add_argument("--confirm", action="store_true", help="Required with --post")
    pl.set_defaults(func=cmd_place_limit)

    pm = sub.add_parser("place-market", help="Create/post market order")
    pm.add_argument("--token-id", required=True)
    pm.add_argument("--amount", type=float, required=True, help="USDC notional amount")
    pm.add_argument("--side", choices=["BUY", "SELL"], required=True)
    pm.add_argument("--order-type", default="FOK", choices=["FOK", "GTC", "GTD"])
    pm.add_argument("--post", action="store_true", help="Post order to exchange")
    pm.add_argument("--confirm", action="store_true", help="Required with --post")
    pm.set_defaults(func=cmd_place_market)

    cancel = sub.add_parser("cancel", help="Cancel one or many order IDs")
    cancel.add_argument("order_ids", nargs="+")
    cancel.add_argument("--confirm", action="store_true")
    cancel.set_defaults(func=cmd_cancel)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
