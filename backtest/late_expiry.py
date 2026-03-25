import argparse
import sqlite3
from collections import defaultdict

from data.storage import DB_PATH, init_db


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def estimate_slippage(spread, depth_top5, stake_usd, latency_ms, extra_slippage):
    spread = max(0.0, float(spread or 0.0))
    depth = max(1.0, float(depth_top5 or 0.0))
    impact = min(0.03, (stake_usd / depth) * 0.10)
    latency_penalty = min(0.02, spread * min(1.5, latency_ms / 500.0))
    return max(0.0, float(extra_slippage or 0.0)) + impact + latency_penalty


def load_end_times(coin_filter=None, timeframe_filter=None):
    init_db()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()
    sql = """
        SELECT market_id, MAX(end_time) AS end_time
        FROM market_prices
        WHERE market_id IS NOT NULL AND end_time IS NOT NULL
    """
    params = []
    if coin_filter:
        ph = ",".join(["?"] * len(coin_filter))
        sql += f" AND lower(coin) IN ({ph})"
        params.extend(sorted(coin_filter))
    if timeframe_filter:
        ph = ",".join(["?"] * len(timeframe_filter))
        sql += f" AND timeframe IN ({ph})"
        params.extend(sorted(timeframe_filter))
    sql += " GROUP BY market_id"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return {
        str(market_id): int(end_time)
        for market_id, end_time in rows
        if market_id and end_time
    }


def load_ws_rows(coin_filter=None, timeframe_filter=None, rows_limit=0):
    init_db()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()
    sql = """
        SELECT
            ts_ms, token_id, market_id, coin, timeframe,
            best_bid, best_ask, mid, spread, depth_top5, last_trade_price
        FROM ws_ticks
        WHERE market_id IS NOT NULL
    """
    params = []
    if coin_filter:
        ph = ",".join(["?"] * len(coin_filter))
        sql += f" AND lower(coin) IN ({ph})"
        params.extend(sorted(coin_filter))
    if timeframe_filter:
        ph = ",".join(["?"] * len(timeframe_filter))
        sql += f" AND timeframe IN ({ph})"
        params.extend(sorted(timeframe_filter))
    sql += " ORDER BY ts_ms"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    if rows_limit and rows_limit > 0 and len(rows) > rows_limit:
        rows = rows[-rows_limit:]
    return rows


def token_entry_price(
    side, bid, ask, mid, spread, depth, stake_usd, latency_ms, extra_slippage
):
    if (not bid or bid <= 0) and (not ask or ask <= 0):
        if not mid or mid <= 0:
            return None
        half = max(float(spread or 0.02) / 2.0, 0.001)
        bid = clamp(mid - half, 0.001, 0.999)
        ask = clamp(mid + half, 0.001, 0.999)
    spread_now = max(0.0, float((ask - bid) if ask and bid else (spread or 0.0)))
    slip = estimate_slippage(spread_now, depth, stake_usd, latency_ms, extra_slippage)
    if side == "BUY YES":
        return clamp(float(ask) + slip, 0.01, 0.99)
    return clamp((1.0 - float(bid)) + slip, 0.01, 0.99)


def token_exit_price(
    side, bid, ask, mid, spread, depth, stake_usd, latency_ms, extra_slippage
):
    if (not bid or bid <= 0) and (not ask or ask <= 0):
        if not mid or mid <= 0:
            return None
        half = max(float(spread or 0.02) / 2.0, 0.001)
        bid = clamp(mid - half, 0.001, 0.999)
        ask = clamp(mid + half, 0.001, 0.999)
    spread_now = max(0.0, float((ask - bid) if ask and bid else (spread or 0.0)))
    slip = estimate_slippage(spread_now, depth, stake_usd, latency_ms, extra_slippage)
    if side == "BUY YES":
        return clamp(float(bid) - slip, 0.001, 0.999)
    return clamp((1.0 - float(ask)) - slip, 0.001, 0.999)


def run_late_expiry(
    rows,
    end_times,
    entry_low=0.80,
    entry_high=0.90,
    seconds_to_expiry=45,
    max_spread=0.03,
    min_depth=100.0,
    stake_usd=10.0,
    latency_ms=250,
    extra_slippage=0.001,
):
    active = {}
    closed = []
    by_timeframe = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl_usd": 0.0})
    by_side = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl_usd": 0.0})

    for (
        ts_ms,
        token_id,
        market_id,
        coin,
        timeframe,
        best_bid,
        best_ask,
        mid,
        spread,
        depth_top5,
        last_trade_price,
    ) in rows:
        market_key = str(market_id or token_id or "")
        if not market_key:
            continue
        end_time = end_times.get(market_key)
        if not end_time:
            continue

        ts_sec = int(ts_ms) // 1000
        spread = float(spread or 0.0)
        depth = float(depth_top5 or 0.0)
        if spread > max_spread:
            continue
        if depth > 0 and depth < min_depth:
            continue

        mid_val = None
        if mid is not None and 0 < float(mid) < 1:
            mid_val = float(mid)
        elif (
            best_bid is not None
            and best_ask is not None
            and float(best_bid) > 0
            and float(best_ask) > 0
        ):
            mid_val = (float(best_bid) + float(best_ask)) / 2.0
        elif last_trade_price is not None and 0 < float(last_trade_price) < 1:
            mid_val = float(last_trade_price)
        if mid_val is None:
            continue

        # Exit at the first quote after expiry.
        if market_key in active and ts_sec >= end_time:
            tr = active[market_key]
            exit_px = token_exit_price(
                tr["side"],
                float(best_bid) if best_bid is not None else None,
                float(best_ask) if best_ask is not None else None,
                mid_val,
                spread,
                depth,
                stake_usd,
                latency_ms,
                extra_slippage,
            )
            if exit_px is None:
                continue
            gross = (exit_px - tr["entry_px"]) / max(tr["entry_px"], 1e-9)
            net = gross - 0.0004
            pnl_usd = net * stake_usd
            closed.append(net)
            by_timeframe[tr["timeframe"]]["trades"] += 1
            by_timeframe[tr["timeframe"]]["wins"] += 1 if net > 0 else 0
            by_timeframe[tr["timeframe"]]["pnl_usd"] += pnl_usd
            by_side[tr["side"]]["trades"] += 1
            by_side[tr["side"]]["wins"] += 1 if net > 0 else 0
            by_side[tr["side"]]["pnl_usd"] += pnl_usd
            del active[market_key]
            continue

        if market_key in active:
            continue

        remaining = end_time - ts_sec
        if remaining <= 0 or remaining > seconds_to_expiry:
            continue

        yes_px = mid_val
        no_px = 1.0 - mid_val
        side = None
        dominant_px = None
        if entry_low <= yes_px <= entry_high and yes_px >= no_px:
            side = "BUY YES"
            dominant_px = yes_px
        elif entry_low <= no_px <= entry_high and no_px > yes_px:
            side = "BUY NO"
            dominant_px = no_px
        if not side or dominant_px is None:
            continue

        entry_px = token_entry_price(
            side,
            float(best_bid) if best_bid is not None else None,
            float(best_ask) if best_ask is not None else None,
            mid_val,
            spread,
            depth,
            stake_usd,
            latency_ms,
            extra_slippage,
        )
        if entry_px is None:
            continue

        active[market_key] = {
            "side": side,
            "entry_px": entry_px,
            "timeframe": str(timeframe or ""),
            "dominant_px": dominant_px,
        }

    n = len(closed)
    wins = [x for x in closed if x > 0]
    losses = [x for x in closed if x <= 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    return {
        "opened": n + len(active),
        "closed": n,
        "open_left": len(active),
        "win_rate": ((len(wins) / n) * 100.0) if n else 0.0,
        "expectancy_pct": (sum(closed) / n) if n else 0.0,
        "profit_factor": (gp / gl) if gl > 0 else 99.0,
        "total_pnl_usd": sum(closed) * stake_usd,
        "by_timeframe": dict(by_timeframe),
        "by_side": dict(by_side),
    }


def print_breakdown(title, bucket):
    print(f"\n{title}")
    print("-" * len(title))
    if not bucket:
        print("(no trades)")
        return
    for key, v in sorted(bucket.items(), key=lambda kv: kv[1]["pnl_usd"], reverse=True):
        n = v["trades"]
        wr = (v["wins"] / n * 100.0) if n else 0.0
        exp = (v["pnl_usd"] / n) if n else 0.0
        print(
            f"{key:>8} | trades={n:4d} | win%={wr:5.1f} | pnl_usd={v['pnl_usd']:+.2f} | exp_usd={exp:+.3f}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Late-expiry dominance replay on ws_ticks."
    )
    parser.add_argument("--coins", default="btc", help="CSV coin allowlist")
    parser.add_argument(
        "--timeframes", default="5m,15m", help="CSV timeframe allowlist"
    )
    parser.add_argument(
        "--rows-limit", type=int, default=200000, help="Latest N ws rows, 0 means all"
    )
    parser.add_argument(
        "--entry-low",
        type=float,
        default=0.80,
        help="Lower bound for dominant side price",
    )
    parser.add_argument(
        "--entry-high",
        type=float,
        default=0.90,
        help="Upper bound for dominant side price",
    )
    parser.add_argument(
        "--seconds-to-expiry",
        type=int,
        default=45,
        help="Only enter this many seconds before end",
    )
    parser.add_argument(
        "--max-spread", type=float, default=0.03, help="Max spread filter"
    )
    parser.add_argument(
        "--min-depth", type=float, default=100.0, help="Min depth_top5 filter"
    )
    parser.add_argument(
        "--stake-usd", type=float, default=10.0, help="Stake used for PnL reporting"
    )
    parser.add_argument(
        "--latency-ms", type=int, default=250, help="Latency proxy in milliseconds"
    )
    parser.add_argument(
        "--extra-slippage",
        type=float,
        default=0.001,
        help="Extra slippage in token price units",
    )
    args = parser.parse_args()

    coin_filter = set([c.strip().lower() for c in args.coins.split(",") if c.strip()])
    tf_filter = set([t.strip() for t in args.timeframes.split(",") if t.strip()])
    end_times = load_end_times(coin_filter=coin_filter, timeframe_filter=tf_filter)
    rows = load_ws_rows(
        coin_filter=coin_filter, timeframe_filter=tf_filter, rows_limit=args.rows_limit
    )
    if not rows:
        print("❌ No ws_ticks rows found for requested filter.")
        return
    if not end_times:
        print("❌ No end_time data found in market_prices for requested filter.")
        return

    print(
        f"Late-expiry replay | rows={len(rows)} | markets={len(end_times)} | "
        f"window={args.seconds_to_expiry}s | entry=[{args.entry_low:.2f},{args.entry_high:.2f}]"
    )
    result = run_late_expiry(
        rows,
        end_times,
        entry_low=args.entry_low,
        entry_high=args.entry_high,
        seconds_to_expiry=args.seconds_to_expiry,
        max_spread=args.max_spread,
        min_depth=args.min_depth,
        stake_usd=args.stake_usd,
        latency_ms=args.latency_ms,
        extra_slippage=args.extra_slippage,
    )

    print("\n" + "=" * 44)
    print("LATE EXPIRY RESULTS")
    print("=" * 44)
    print(f"Opened Trades: {result['opened']}")
    print(f"Closed Trades: {result['closed']}")
    print(f"Open Left: {result['open_left']}")
    print(f"Win Rate: {result['win_rate']:.2f}%")
    print(f"Expectancy: {result['expectancy_pct']:+.4f} (pct per trade)")
    print(f"Profit Factor: {result['profit_factor']:.2f}")
    print(f"Total PnL: {result['total_pnl_usd']:+.2f} USD")
    print_breakdown("PER-TIMEFRAME", result["by_timeframe"])
    print_breakdown("PER-SIDE", result["by_side"])


if __name__ == "__main__":
    main()
