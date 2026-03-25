import argparse
import math
import sqlite3
from collections import defaultdict

from app.config import (
    RISK_PROFILES,
    SELECTED_RISK_PROFILE_NAME,
    SIZING_PROFILES,
    SELECTED_SIZING_PROFILE_NAME,
)
from backtest.common import detect_regime
from data.storage import DB_PATH, init_db
from features.builder import build_features
from strategy.signal import generate_mean_reversion_signal, generate_trend_signal


MAX_HOLD_BY_TF_SEC = {
    "5m": 15 * 60,
    "15m": 45 * 60,
    "1h": 2 * 60 * 60,
    "4h": 6 * 60 * 60,
}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def estimate_slippage(spread, depth_top5, stake_usd, latency_ms, extra_slippage):
    spread = max(0.0, float(spread or 0.0))
    depth = max(1.0, float(depth_top5 or 0.0))
    # Simple impact model: larger stake versus local depth increases slip.
    impact = min(0.03, (stake_usd / depth) * 0.10)
    # Latency penalty as a spread-proportional drift proxy.
    latency_penalty = min(0.02, spread * min(1.5, latency_ms / 500.0))
    return max(0.0, float(extra_slippage or 0.0)) + impact + latency_penalty


def resolve_stake_usd(default_value=10.0):
    profile = SIZING_PROFILES.get(
        SELECTED_SIZING_PROFILE_NAME, SIZING_PROFILES.get("FIXED", {})
    )
    if profile.get("type") == "fixed":
        try:
            return float(profile.get("value", default_value))
        except Exception:
            return default_value
    return default_value


def load_ws_rows(profile, start_ts_ms=None, end_ts_ms=None, rows_limit=0):
    init_db()
    allowed_coins = set(
        [str(c).lower() for c in profile.get("trade_allowed_coins", [])]
    )
    allowed_tfs = set([str(tf) for tf in profile.get("trade_allowed_timeframes", [])])
    blocked_tfs = set([str(tf) for tf in profile.get("blocked_timeframes", [])])

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ws_ticks'")
    if not cur.fetchone():
        conn.close()
        return []

    sql = """
        SELECT
            ts_ms, token_id, market_id, coin, timeframe,
            best_bid, best_ask, mid, spread,
            bid_sz_top5, ask_sz_top5, depth_top5, pressure, last_trade_price
        FROM ws_ticks
    """
    wheres = []
    params = []
    if start_ts_ms:
        wheres.append("ts_ms >= ?")
        params.append(int(start_ts_ms))
    if end_ts_ms:
        wheres.append("ts_ms <= ?")
        params.append(int(end_ts_ms))
    if allowed_coins:
        ph = ",".join(["?"] * len(allowed_coins))
        wheres.append(f"lower(coin) IN ({ph})")
        params.extend(sorted(allowed_coins))
    if allowed_tfs:
        ph = ",".join(["?"] * len(allowed_tfs))
        wheres.append(f"timeframe IN ({ph})")
        params.extend(sorted(allowed_tfs))
    if blocked_tfs:
        ph = ",".join(["?"] * len(blocked_tfs))
        wheres.append(f"timeframe NOT IN ({ph})")
        params.extend(sorted(blocked_tfs))
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY ts_ms"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    if rows_limit and rows_limit > 0 and len(rows) > rows_limit:
        rows = rows[-rows_limit:]
    return rows


def run_replay(
    rows,
    profile,
    stake_usd=10.0,
    latency_ms=250,
    extra_slippage=0.001,
):
    if not rows:
        return {
            "opened": 0,
            "closed": 0,
            "win_rate": 0.0,
            "expectancy_pct": 0.0,
            "profit_factor": 0.0,
            "total_pnl_pct": 0.0,
            "total_pnl_usd": 0.0,
            "forced_closes": 0,
            "by_coin": {},
            "by_timeframe": {},
            "by_regime": {},
        }

    tp_pct = float(profile.get("tp_pct", 0.10))
    sl_pct = float(profile.get("sl_pct", 0.05))
    max_spread = float(profile.get("max_spread", 0.08))
    min_depth = float(profile.get("min_depth_top5", 0))
    min_effective_ev = float(profile.get("min_effective_ev", 0.0))
    max_signal_age_sec = int(profile.get("max_signal_age_sec", 60))
    signal_decay_lambda = float(profile.get("signal_decay_lambda", 0.02))
    max_entries_per_cycle = int(profile.get("max_entries_per_cycle", 3))

    history = {}
    btc_history = {}
    signal_state = {}
    candidates = []
    active = {}
    last_state_by_market = {}
    last_quote_by_market = {}
    opened = 0
    forced_closes = 0
    closed_pnls_pct = []
    by_coin = defaultdict(
        lambda: {"trades": 0, "wins": 0, "pnl_pct": 0.0, "pnl_usd": 0.0}
    )
    by_timeframe = defaultdict(
        lambda: {"trades": 0, "wins": 0, "pnl_pct": 0.0, "pnl_usd": 0.0}
    )
    by_regime = defaultdict(
        lambda: {"trades": 0, "wins": 0, "pnl_pct": 0.0, "pnl_usd": 0.0}
    )
    current_cycle = None

    def token_entry_price(side, bid, ask, mid, spread, depth):
        if (not bid or bid <= 0) and (not ask or ask <= 0):
            if not mid or mid <= 0:
                return None
            half = max(float(spread or 0.02) / 2.0, 0.001)
            bid = clamp(mid - half, 0.001, 0.999)
            ask = clamp(mid + half, 0.001, 0.999)
        spread_now = max(0.0, float((ask - bid) if ask and bid else (spread or 0.0)))
        slip = estimate_slippage(
            spread_now, depth, stake_usd, latency_ms, extra_slippage
        )
        if side == "BUY YES":
            return clamp(float(ask) + slip, 0.01, 0.99)
        return clamp((1.0 - float(bid)) + slip, 0.01, 0.99)

    def token_exit_price(side, bid, ask, mid, spread, depth):
        if (not bid or bid <= 0) and (not ask or ask <= 0):
            if not mid or mid <= 0:
                return None
            half = max(float(spread or 0.02) / 2.0, 0.001)
            bid = clamp(mid - half, 0.001, 0.999)
            ask = clamp(mid + half, 0.001, 0.999)
        spread_now = max(0.0, float((ask - bid) if ask and bid else (spread or 0.0)))
        slip = estimate_slippage(
            spread_now, depth, stake_usd, latency_ms, extra_slippage
        )
        if side == "BUY YES":
            return clamp(float(bid) - slip, 0.001, 0.999)
        return clamp((1.0 - float(ask)) - slip, 0.001, 0.999)

    def close_trade(market_key, exit_token_px, reason):
        nonlocal forced_closes
        tr = active.get(market_key)
        if not tr:
            return
        gross = (exit_token_px - tr["entry_token_px"]) / max(tr["entry_token_px"], 1e-9)
        # Roundtrip fees proxy, 2 bps each leg (0.04% total)
        net = gross - 0.0004
        pnl_usd = net * stake_usd
        closed_pnls_pct.append(net)
        b1 = by_coin[tr["coin"]]
        b2 = by_timeframe[tr["timeframe"]]
        b3 = by_regime[tr["regime"]]
        for b in [b1, b2, b3]:
            b["trades"] += 1
            b["wins"] += 1 if net > 0 else 0
            b["pnl_pct"] += net
            b["pnl_usd"] += pnl_usd
        if reason == "FORCE":
            forced_closes += 1
        del active[market_key]

    def flush_candidates():
        nonlocal opened, candidates
        if not candidates:
            return
        ranked = sorted(candidates, key=lambda x: x["decayed_ev"], reverse=True)
        used = 0
        for c in ranked:
            if used >= max_entries_per_cycle:
                break
            key = c["market_key"]
            if key in active:
                continue
            entry_px = token_entry_price(
                c["side"],
                c["bid"],
                c["ask"],
                c["mid"],
                c["spread"],
                c["depth_top5"],
            )
            if entry_px is None:
                continue
            active[key] = {
                "side": c["side"],
                "entry_token_px": entry_px,
                "entry_ts": c["ts_ms"] // 1000,
                "coin": c["coin"],
                "timeframe": c["timeframe"],
                "regime": c["regime"],
            }
            opened += 1
            used += 1
        candidates = []

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
        bid_sz_top5,
        ask_sz_top5,
        depth_top5,
        pressure,
        last_trade_price,
    ) in rows:
        market_key = market_id or token_id
        if not market_key:
            continue

        coin = (coin or "").lower()
        timeframe = str(timeframe or "")
        if not timeframe:
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

        cycle = int(ts_ms) // 60000
        if current_cycle is None:
            current_cycle = cycle
        elif cycle != current_cycle:
            flush_candidates()
            current_cycle = cycle

        quote = {
            "bid": float(best_bid) if best_bid is not None else None,
            "ask": float(best_ask) if best_ask is not None else None,
            "mid": mid_val,
            "spread": float(spread) if spread is not None else 0.0,
            "depth_top5": float(depth_top5) if depth_top5 is not None else 0.0,
            "pressure": float(pressure) if pressure is not None else None,
        }
        last_quote_by_market[market_key] = quote

        series = history.setdefault(market_key, [])
        series.append(mid_val)
        series = series[-30:]
        history[market_key] = series

        if coin == "btc":
            btc_series = btc_history.setdefault(timeframe, [])
            btc_series.append(mid_val)
            btc_history[timeframe] = btc_series[-40:]

        # EXIT first
        if market_key in active:
            tr = active[market_key]
            cur_token_px = token_exit_price(
                tr["side"],
                quote["bid"],
                quote["ask"],
                quote["mid"],
                quote["spread"],
                quote["depth_top5"],
            )
            if cur_token_px is not None:
                move_pct = (cur_token_px - tr["entry_token_px"]) / max(
                    tr["entry_token_px"], 1e-9
                )
                hold_sec = (int(ts_ms) // 1000) - tr["entry_ts"]
                max_hold = MAX_HOLD_BY_TF_SEC.get(tr["timeframe"], 15 * 60)

                state = last_state_by_market.get(market_key, {})
                early_reason = None
                effective_ev = state.get("effective_ev")
                p_val = state.get("pressure", 0.0)
                if effective_ev is not None and effective_ev < -0.01:
                    early_reason = "EV_FLIP"
                if tr["side"] == "BUY YES" and p_val < -0.20:
                    early_reason = early_reason or "PRESSURE_FLIP"
                if tr["side"] == "BUY NO" and p_val > 0.20:
                    early_reason = early_reason or "PRESSURE_FLIP"
                if hold_sec >= max_hold:
                    early_reason = early_reason or "TIME"

                if move_pct >= tp_pct or move_pct <= -sl_pct or early_reason:
                    close_trade(market_key, cur_token_px, early_reason or "TP_SL")

        features = build_features(series, volume=1000.0, oi_series=None)
        if not features or len(series) < 20:
            continue
        features["current_spread"] = quote["spread"]
        if quote["pressure"] is not None:
            features["pressure"] = quote["pressure"]
        else:
            features["pressure"] = math.tanh(features.get("z_score", 0.0) / 2.0)
        features["depth_top5"] = quote["depth_top5"]

        btc_series = btc_history.get(timeframe, [])[-20:]
        btc_up = True
        btc_down = True
        if len(btc_series) >= 10:
            btc_sma = sum(btc_series) / len(btc_series)
            btc_now = btc_series[-1]
            btc_up = btc_now > btc_sma
            btc_down = btc_now < btc_sma

        market_context = {
            "btc_trending_up": btc_up,
            "btc_trending_down": btc_down,
            "timeframe": timeframe,
            "coin": coin,
        }
        regime = detect_regime(features, timeframe)
        market_context["regime"] = regime
        if regime == "volatile":
            signal, confidence = None, 0.0
        elif timeframe in ["1h", "4h"] or regime == "trend":
            signal, confidence = generate_trend_signal(
                features, profile, market_context
            )
        else:
            signal, confidence = generate_mean_reversion_signal(
                features, profile, market_context
            )

        z_strength = min(abs(features.get("z_score", 0.0)) / 3.0, 1.0)
        base_conf = 0.5 + (z_strength * 0.2)
        base_ev = (base_conf * 0.10) - ((1.0 - base_conf) * 0.05)
        last_state_by_market[market_key] = {
            "effective_ev": base_ev,
            "pressure": features.get("pressure", 0.0),
            "regime": regime,
        }

        if not signal:
            signal_state.pop(market_key, None)
            continue

        if quote["spread"] > max_spread:
            continue
        if quote["depth_top5"] > 0 and quote["depth_top5"] < min_depth:
            continue

        raw_ev = (confidence * 0.10) - ((1.0 - confidence) * 0.05)
        spread_cost = (quote["spread"] / max(mid_val, 0.20)) * 0.5
        slippage_cost = 0.005
        effective_ev = raw_ev - spread_cost - slippage_cost
        if effective_ev < min_effective_ev:
            continue

        state = signal_state.get(market_key)
        now_sec = int(ts_ms) // 1000
        if state and state.get("side") == signal:
            first_seen = state.get("first_seen", now_sec)
        else:
            first_seen = now_sec
            signal_state[market_key] = {"side": signal, "first_seen": first_seen}

        age = max(0, now_sec - first_seen)
        if age > max_signal_age_sec:
            continue
        decay = math.exp(-signal_decay_lambda * age)
        decayed_ev = effective_ev * decay
        if decayed_ev < min_effective_ev:
            continue

        candidates.append(
            {
                "market_key": market_key,
                "side": signal,
                "coin": coin,
                "timeframe": timeframe,
                "regime": regime,
                "ts_ms": int(ts_ms),
                "mid": mid_val,
                "bid": quote["bid"],
                "ask": quote["ask"],
                "spread": quote["spread"],
                "depth_top5": quote["depth_top5"],
                "decayed_ev": decayed_ev,
            }
        )

    flush_candidates()

    # Force close anything still open on final mark.
    for market_key, tr in list(active.items()):
        quote = last_quote_by_market.get(market_key)
        if not quote:
            continue
        exit_px = token_exit_price(
            tr["side"],
            quote["bid"],
            quote["ask"],
            quote["mid"],
            quote["spread"],
            quote["depth_top5"],
        )
        if exit_px is None:
            continue
        close_trade(market_key, exit_px, "FORCE")

    n = len(closed_pnls_pct)
    if n == 0:
        pf = 0.0
        win_rate = 0.0
        expectancy = 0.0
        total_pct = 0.0
        total_usd = 0.0
        gp = 0.0
        gl = 0.0
        wins_count = 0
        losses_count = 0
    else:
        wins = [x for x in closed_pnls_pct if x > 0]
        losses = [x for x in closed_pnls_pct if x <= 0]
        wins_count = len(wins)
        losses_count = len(losses)
        gp = sum(wins)
        gl = abs(sum(losses))
        pf = (gp / gl) if gl > 0 else 99.0
        win_rate = (len(wins) / n) * 100.0
        expectancy = sum(closed_pnls_pct) / n
        total_pct = sum(closed_pnls_pct)
        total_usd = total_pct * stake_usd

    return {
        "opened": opened,
        "closed": n,
        "wins": wins_count,
        "losses": losses_count,
        "win_rate": win_rate,
        "expectancy_pct": expectancy,
        "profit_factor": pf,
        "total_pnl_pct": total_pct,
        "total_pnl_usd": total_usd,
        "gross_profit_pct": gp,
        "gross_loss_pct": gl,
        "forced_closes": forced_closes,
        "by_coin": dict(by_coin),
        "by_timeframe": dict(by_timeframe),
        "by_regime": dict(by_regime),
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
        description="Replay backtest using ws_ticks table."
    )
    parser.add_argument(
        "--profile",
        default=SELECTED_RISK_PROFILE_NAME,
        help="Risk profile name from config",
    )
    parser.add_argument(
        "--rows-limit",
        type=int,
        default=200000,
        help="Use only latest N ws rows for faster iteration. 0 means all rows.",
    )
    parser.add_argument(
        "--start-ts-ms", type=int, default=0, help="Optional start ts_ms"
    )
    parser.add_argument("--end-ts-ms", type=int, default=0, help="Optional end ts_ms")
    parser.add_argument(
        "--latency-ms",
        type=int,
        default=250,
        help="Latency penalty proxy in milliseconds.",
    )
    parser.add_argument(
        "--extra-slippage",
        type=float,
        default=0.001,
        help="Additional slippage (absolute token price units).",
    )
    args = parser.parse_args()

    profile = RISK_PROFILES.get(args.profile, RISK_PROFILES.get("BALANCED", {}))
    rows = load_ws_rows(
        profile,
        start_ts_ms=args.start_ts_ms if args.start_ts_ms > 0 else None,
        end_ts_ms=args.end_ts_ms if args.end_ts_ms > 0 else None,
        rows_limit=args.rows_limit,
    )
    if not rows:
        print("❌ No ws_ticks rows found for this profile/filter.")
        return

    stake_usd = resolve_stake_usd(default_value=10.0)
    print(
        f"🎬 Replay using profile={args.profile} | rows={len(rows)} | latency_ms={args.latency_ms} | extra_slippage={args.extra_slippage}"
    )
    result = run_replay(
        rows,
        profile,
        stake_usd=stake_usd,
        latency_ms=args.latency_ms,
        extra_slippage=args.extra_slippage,
    )
    print("\n" + "=" * 44)
    print(f"REPLAY RESULTS ({args.profile})")
    print("=" * 44)
    print(f"Opened Trades: {result['opened']}")
    print(f"Closed Trades: {result['closed']}")
    print(f"Forced Closes: {result['forced_closes']}")
    print(f"Win Rate: {result['win_rate']:.2f}%")
    print(f"Expectancy: {result['expectancy_pct']:+.4f} (pct per trade)")
    print(f"Profit Factor: {result['profit_factor']:.2f}")
    print(f"Total PnL: {result['total_pnl_usd']:+.2f} USD")
    print_breakdown("PER-COIN", result["by_coin"])
    print_breakdown("PER-TIMEFRAME", result["by_timeframe"])
    print_breakdown("PER-REGIME", result["by_regime"])


if __name__ == "__main__":
    main()
