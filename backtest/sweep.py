import argparse
import itertools
import math
import sqlite3
import json
from pathlib import Path

from app.config import RISK_PROFILES, SELECTED_RISK_PROFILE_NAME, CONFIG_PATH
from data.storage import DB_PATH
from features.builder import build_features
from strategy.signal import generate_mean_reversion_signal, generate_trend_signal


TP_PCT = 0.10
SL_PCT = 0.05
MAX_HOLD_BY_TF_SEC = {
    "5m": 15 * 60,
    "15m": 45 * 60,
    "1h": 2 * 60 * 60,
    "4h": 6 * 60 * 60,
}
ASSUMED_SPREAD_BY_TF = {
    "5m": 0.03,
    "15m": 0.025,
    "1h": 0.02,
    "4h": 0.018,
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BEST_PARAMS_PATH = str(PROJECT_ROOT / "db" / "best_params.json")


def detect_regime(features, timeframe):
    rel_vol = features.get("rel_vol", 1.0)
    momentum_pct = abs(features.get("momentum_pct", 0.0))
    z_abs = abs(features.get("z_score", 0.0))
    if rel_vol >= 1.35:
        return "volatile"
    if timeframe in ["1h", "4h"]:
        return "trend" if z_abs >= 0.8 or momentum_pct >= 0.02 else "range"
    return "trend" if z_abs >= 1.5 or momentum_pct >= 0.03 else "range"


def load_rows():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT market_id, question, coin, timeframe, price, timestamp
        FROM market_prices
        ORDER BY timestamp
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def run_once(
    rows,
    base_profile,
    min_effective_ev,
    signal_decay_lambda,
    max_signal_age_sec,
    max_entries_per_cycle,
    tp_pct,
    sl_pct,
    disable_trend=False,
    allowed_coins=None,
    allowed_timeframes=None,
):
    profile = dict(base_profile)
    profile["min_effective_ev"] = min_effective_ev
    profile["signal_decay_lambda"] = signal_decay_lambda
    profile["max_signal_age_sec"] = max_signal_age_sec
    profile["max_entries_per_cycle"] = max_entries_per_cycle

    history = {}
    btc_history = {}
    signal_state = {}
    active = {}
    candidates = []
    closed_pnls = []
    opened_count = 0
    last_yes_price = {}

    current_cycle = None

    def flush_candidates():
        nonlocal candidates, opened_count
        if not candidates:
            return
        ranked = sorted(candidates, key=lambda x: x["decayed_ev"], reverse=True)
        opened = 0
        for c in ranked:
            if opened >= max_entries_per_cycle:
                break
            if c["market_id"] in active:
                continue
            side = c["side"]
            yes_entry = c["price"]
            token_entry = yes_entry if side == "BUY YES" else (1.0 - yes_entry)
            if token_entry <= 0:
                continue
            active[c["market_id"]] = {
                "side": side,
                "token_entry": token_entry,
                "entry_ts": c["timestamp"],
                "timeframe": c["timeframe"],
            }
            opened += 1
            opened_count += 1
        candidates = []

    for market_id, question, coin, timeframe, price, ts in rows:
        coin_key = (coin or "").lower()
        if allowed_coins and coin_key not in allowed_coins:
            continue
        if allowed_timeframes and timeframe not in allowed_timeframes:
            continue

        last_yes_price[market_id] = price
        cycle = ts // 60
        if current_cycle is None:
            current_cycle = cycle
        elif cycle != current_cycle:
            flush_candidates()
            current_cycle = cycle

        if market_id not in history:
            history[market_id] = []
        history[market_id].append(price)
        series = history[market_id][-30:]

        if coin == "btc":
            if timeframe not in btc_history:
                btc_history[timeframe] = []
            btc_history[timeframe].append(price)

        # Exit logic
        if market_id in active:
            tr = active[market_id]
            cur_token = price if tr["side"] == "BUY YES" else (1.0 - price)
            move_pct = (cur_token - tr["token_entry"]) / tr["token_entry"]
            hold_sec = ts - tr["entry_ts"]
            max_hold_sec = MAX_HOLD_BY_TF_SEC.get(tr["timeframe"], 15 * 60)
            if move_pct >= tp_pct or move_pct <= -sl_pct or hold_sec >= max_hold_sec:
                closed_pnls.append(move_pct)
                del active[market_id]

        features = build_features(series, volume=1000, oi_series=None)
        if not features:
            continue

        features["pressure"] = math.tanh(features.get("z_score", 0.0) / 2.0)
        btc_series = btc_history.get(timeframe, [])[-20:]
        btc_up = True
        btc_down = True
        if len(btc_series) >= 10:
            btc_sma = sum(btc_series) / len(btc_series)
            btc_now = btc_series[-1]
            btc_up = btc_now > btc_sma
            btc_down = btc_now < btc_sma

        context = {
            "btc_trending_up": btc_up,
            "btc_trending_down": btc_down,
            "timeframe": timeframe,
        }

        regime = detect_regime(features, timeframe)
        if regime == "volatile":
            signal, confidence = None, 0.0
        elif timeframe in ["1h", "4h"] or regime == "trend":
            if disable_trend:
                signal, confidence = None, 0.0
            else:
                signal, confidence = generate_trend_signal(features, profile, context)
        else:
            signal, confidence = generate_mean_reversion_signal(
                features, profile, context
            )

        if not signal:
            signal_state.pop(market_id, None)
            continue

        raw_ev = (confidence * 0.10) - ((1.0 - confidence) * 0.05)
        spread = ASSUMED_SPREAD_BY_TF.get(timeframe, 0.03)
        spread_cost = (spread / max(price, 0.20)) * 0.5
        effective_ev = raw_ev - spread_cost - 0.005
        if effective_ev < min_effective_ev:
            continue

        state = signal_state.get(market_id)
        now = int(ts)
        if state and state.get("side") == signal:
            first_seen = state.get("first_seen", now)
        else:
            first_seen = now
            signal_state[market_id] = {"side": signal, "first_seen": first_seen}
        age = now - first_seen
        if age > max_signal_age_sec:
            continue

        decay = math.exp(-signal_decay_lambda * age)
        decayed_ev = effective_ev * decay
        if decayed_ev < min_effective_ev:
            continue

        candidates.append(
            {
                "market_id": market_id,
                "side": signal,
                "price": price,
                "timeframe": timeframe,
                "timestamp": ts,
                "decayed_ev": decayed_ev,
            }
        )

    flush_candidates()
    # Force-close remaining active trades at the last known mark.
    for m_id, tr in list(active.items()):
        yes_price = last_yes_price.get(m_id)
        if yes_price is None:
            continue
        cur_token = yes_price if tr["side"] == "BUY YES" else (1.0 - yes_price)
        move_pct = (cur_token - tr["token_entry"]) / tr["token_entry"]
        closed_pnls.append(move_pct)
        del active[m_id]

    n = len(closed_pnls)
    if n == 0:
        return {
            "opened": opened_count,
            "trades": 0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "score": 0.0,
        }
    wins = [p for p in closed_pnls if p > 0]
    losses = [p for p in closed_pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.0
    expectancy = sum(closed_pnls) / n
    score = expectancy * math.sqrt(n)
    return {
        "opened": opened_count,
        "trades": n,
        "win_rate": (len(wins) / n) * 100.0,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "total_pnl": sum(closed_pnls),
        "score": score,
    }


def parse_float_list(raw):
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def parse_int_list(raw):
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def normalize_rows_limit(value):
    # Treat 0 or negative values as "use all rows".
    return 0 if value is None or value <= 0 else value


def save_best_params(path, payload):
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as f:
        json.dump(payload, f, indent=2)


def apply_best_to_config(best, profile_name):
    cfg_path = Path(CONFIG_PATH)
    with cfg_path.open("r") as f:
        cfg = json.load(f)

    risk_profiles = cfg.get("risk_profiles", {})
    if profile_name not in risk_profiles:
        raise ValueError(f"Profile '{profile_name}' not found in config.json")

    risk_profiles[profile_name]["min_effective_ev"] = best["min_effective_ev"]
    risk_profiles[profile_name]["signal_decay_lambda"] = best["signal_decay_lambda"]
    risk_profiles[profile_name]["max_signal_age_sec"] = best["max_signal_age_sec"]
    risk_profiles[profile_name]["max_entries_per_cycle"] = best["max_entries_per_cycle"]
    if "tp_pct" in best:
        risk_profiles[profile_name]["tp_pct"] = best["tp_pct"]
    if "sl_pct" in best:
        risk_profiles[profile_name]["sl_pct"] = best["sl_pct"]

    with cfg_path.open("w") as f:
        json.dump(cfg, f, indent=4)


def main():
    parser = argparse.ArgumentParser(
        description="Grid sweep for non-ML Polymarket strategy parameters."
    )
    parser.add_argument(
        "--profile",
        default=SELECTED_RISK_PROFILE_NAME,
        help="Risk profile name from config.json",
    )
    parser.add_argument("--top", type=int, default=10, help="Top N results to print")
    parser.add_argument(
        "--rows-limit",
        type=int,
        default=5000,
        help="Use only latest N rows for fast iteration",
    )
    parser.add_argument(
        "--min-ev",
        default="0.010,0.015,0.020",
        help="CSV list for min_effective_ev grid",
    )
    parser.add_argument(
        "--decay", default="0.010,0.020", help="CSV list for signal_decay_lambda grid"
    )
    parser.add_argument(
        "--age", type=int, default=45, help="Fixed max_signal_age_sec value"
    )
    parser.add_argument(
        "--topn", default="2,3", help="CSV list for max_entries_per_cycle grid"
    )
    parser.add_argument(
        "--tp", default=f"{TP_PCT}", help="CSV list for take-profit pct grid"
    )
    parser.add_argument(
        "--sl", default=f"{SL_PCT}", help="CSV list for stop-loss pct grid"
    )
    parser.add_argument(
        "--disable-trend",
        action="store_true",
        help="Skip trend regime entries (mean-reversion only)",
    )
    parser.add_argument(
        "--coins",
        default="",
        help="CSV allowlist of coins (lowercase) to include in sweep",
    )
    parser.add_argument(
        "--timeframes",
        default="",
        help="CSV allowlist of timeframes to include in sweep (e.g. 5m,15m)",
    )
    parser.add_argument(
        "--save-best",
        default=DEFAULT_BEST_PARAMS_PATH,
        help="Where to write best params JSON",
    )
    parser.add_argument(
        "--apply-best",
        action="store_true",
        help="Apply best params to selected profile in config.json",
    )
    parser.add_argument(
        "--min-closed-for-apply",
        type=int,
        default=30,
        help="Minimum closed trades required before apply-best can modify config",
    )
    args = parser.parse_args()

    base_profile = RISK_PROFILES.get(args.profile, RISK_PROFILES.get("MAIN", {}))
    rows = load_rows()
    if not rows:
        print("No historical rows in DB.")
        return
    rows_limit = normalize_rows_limit(args.rows_limit)
    print(
        f"Sweep rows-limit: {'ALL' if rows_limit == 0 else rows_limit} | total_rows={len(rows)}"
    )
    if rows_limit > 0 and len(rows) > rows_limit:
        rows = rows[-rows_limit:]

    grid_min_ev = parse_float_list(args.min_ev)
    grid_decay = parse_float_list(args.decay)
    grid_topn = parse_int_list(args.topn)
    grid_tp = parse_float_list(args.tp)
    grid_sl = parse_float_list(args.sl)

    allowed_coins = set([c.strip().lower() for c in args.coins.split(",") if c.strip()])
    allowed_timeframes = set([t.strip() for t in args.timeframes.split(",") if t.strip()])

    results = []
    combos = list(
        itertools.product(
            grid_min_ev, grid_decay, grid_topn, grid_tp, grid_sl
        )
    )
    for i, (min_ev, decay, topn, tp_pct, sl_pct) in enumerate(combos, start=1):
        print(
            f"[{i}/{len(combos)}] min_ev={min_ev:.3f} decay={decay:.3f} age={args.age} topN={topn} tp={tp_pct:.3f} sl={sl_pct:.3f}"
        )
        metrics = run_once(
            rows,
            base_profile,
            min_ev,
            decay,
            args.age,
            topn,
            tp_pct,
            sl_pct,
            disable_trend=args.disable_trend,
            allowed_coins=allowed_coins or None,
            allowed_timeframes=allowed_timeframes or None,
        )
        result = {
            "min_effective_ev": min_ev,
            "signal_decay_lambda": decay,
            "max_signal_age_sec": args.age,
            "max_entries_per_cycle": topn,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            **metrics,
        }
        results.append(result)

    ranked = sorted(
        results,
        key=lambda r: (r["score"], r["profit_factor"], r["trades"]),
        reverse=True,
    )
    if all(r["opened"] == 0 for r in results):
        print(
            "WARNING: no entries opened in this sample. Try --rows-limit 0 or looser strategy thresholds."
        )
    print(f"Sweep runs: {len(results)} | rows_used: {len(rows)}")
    print("=" * 98)
    print(
        "rank | open/closed | win%  | expectancy | pf    | total_pnl | min_ev | decay | age | topN | tp  | sl"
    )
    print("=" * 98)
    for i, r in enumerate(ranked[: args.top], start=1):
        print(
            f"{i:>4} | {r['opened']:>4}/{r['trades']:<6} | {r['win_rate']:>5.1f} | {r['expectancy']:>10.4f} | "
            f"{r['profit_factor']:>5.2f} | {r['total_pnl']:>9.4f} | {r['min_effective_ev']:.3f} | "
            f"{r['signal_decay_lambda']:.3f} | {r['max_signal_age_sec']:>3} | {r['max_entries_per_cycle']:>4} | "
            f"{r['tp_pct']:.3f} | {r['sl_pct']:.3f}"
        )

    best = ranked[0] if ranked else None
    if best:
        payload = {
            "profile": args.profile,
            "rows_used": len(rows),
            "best": best,
            "top": ranked[: args.top],
        }
        save_best_params(args.save_best, payload)
        print(f"\nSaved best params to: {args.save_best}")

        if args.apply_best:
            if best.get("trades", 0) < args.min_closed_for_apply:
                print(
                    f"Skipped apply-best: closed trades {best.get('trades', 0)} < "
                    f"required {args.min_closed_for_apply}."
                )
            else:
                apply_best_to_config(best, args.profile)
                print(f"Applied best params to config.json profile: {args.profile}")


if __name__ == "__main__":
    main()
