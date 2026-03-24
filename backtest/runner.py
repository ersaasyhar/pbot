import sqlite3
import math
from collections import defaultdict
from features.builder import build_features
from strategy.signal import generate_trend_signal, generate_mean_reversion_signal
from backtest.simulator import Trade
from data.storage import DB_PATH
from app.config import RISK_PROFILES, SELECTED_RISK_PROFILE_NAME

# Use the same unified profile as the live bot
PROFILE_NAME = SELECTED_RISK_PROFILE_NAME
PROFILE = RISK_PROFILES.get(PROFILE_NAME, RISK_PROFILES.get("MAIN", {}))


def profile_for_timeframe(timeframe):
    base = PROFILE or {}
    overrides = (base.get("timeframe_overrides", {}) or {}).get(timeframe, {}) or {}
    if not overrides:
        return base
    merged = dict(base)
    merged.update(overrides)
    return merged
def detect_regime(features, timeframe):
    rel_vol = features.get("rel_vol", 1.0)
    momentum_pct = abs(features.get("momentum_pct", 0.0))
    z_abs = abs(features.get("z_score", 0.0))

    if rel_vol >= 1.8:
        return "volatile"
    if timeframe in ["1h", "4h"]:
        return "trend" if z_abs >= 0.8 or momentum_pct >= 0.02 else "range"
    return "trend" if z_abs >= 1.5 or momentum_pct >= 0.03 else "range"


def backtest():
    print(f"📈 Running Backtest using {PROFILE_NAME} profile (Unified Config)...")
    profile = PROFILE
    tp_pct = float(profile.get("tp_pct", 0.10))
    sl_pct = float(profile.get("sl_pct", 0.05))
    allowed_coins = set([str(c).lower() for c in profile.get("trade_allowed_coins", [])])
    allowed_timeframes = set(
        [str(tf) for tf in profile.get("trade_allowed_timeframes", [])]
    )
    blocked_timeframes = set([str(tf) for tf in profile.get("blocked_timeframes", [])])

    if allowed_coins:
        print(f"Backtest coin allowlist: {sorted(allowed_coins)}")
    if allowed_timeframes:
        print(f"Backtest timeframe allowlist: {sorted(allowed_timeframes)}")
    if blocked_timeframes:
        print(f"Backtest blocked timeframes: {sorted(blocked_timeframes)}")
    print(f"Backtest exits (base): TP={tp_pct:.2%} | SL={sl_pct:.2%}")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='market_prices'"
    )
    if not cur.fetchone():
        print("❌ No data found in database.")
        return

    cur.execute("""
        SELECT market_id, question, coin, timeframe, price, timestamp
        FROM market_prices
        ORDER BY timestamp
    """)

    data = cur.fetchall()
    if not data:
        print("❌ Database is empty.")
        return

    history = {}
    btc_history = {}
    last_price_by_market = {}
    trades = []
    active_trades = {}
    pnl_total = 0
    by_coin = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    by_timeframe = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    by_regime = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})

    for row in data:
        market_id, question, coin, timeframe, price, ts = row
        coin_key = (coin or "").lower()
        if allowed_coins and coin_key not in allowed_coins:
            continue
        if allowed_timeframes and timeframe not in allowed_timeframes:
            continue
        if timeframe in blocked_timeframes:
            continue

        last_price_by_market[market_id] = price
        if market_id not in history:
            history[market_id] = []
        history[market_id].append(price)
        series = history[market_id][-30:]

        # Build BTC context by timeframe as a macro filter proxy.
        if coin == "btc":
            if timeframe not in btc_history:
                btc_history[timeframe] = []
            btc_history[timeframe].append(price)

        features = build_features(series, volume=1000, oi_series=None)
        if not features:
            continue

        # Backtest DB does not store order-book depth/pressure snapshots.
        # Use z-score direction as a lightweight pressure proxy.
        features["pressure"] = math.tanh(features.get("z_score", 0.0) / 2.0)

        # ENTRY
        if market_id not in active_trades:
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
                "coin": coin_key,
            }
            profile_tf = profile_for_timeframe(timeframe)
            regime = detect_regime(features, timeframe)
            if regime == "volatile":
                signal, confidence = None, 0.0
            elif timeframe in ["1h", "4h"] or regime == "trend":
                signal, confidence = generate_trend_signal(
                    features, profile_tf, market_context
                )
            else:
                signal, confidence = generate_mean_reversion_signal(
                    features, profile_tf, market_context
                )

            if signal:
                active_trades[market_id] = {
                    "trade": Trade(signal, price),
                    "coin": coin_key,
                    "timeframe": timeframe,
                    "regime": regime,
                }

        # EXIT
        if market_id in active_trades:
            slot = active_trades[market_id]
            trade = slot["trade"]
            pnl = trade.pnl_pct(price)
            profile_tf = profile_for_timeframe(slot["timeframe"])
            tp_pct = float(profile_tf.get("tp_pct", 0.10))
            sl_pct = float(profile_tf.get("sl_pct", 0.05))
            if pnl >= tp_pct or pnl <= -sl_pct:
                pnl_total += pnl
                trades.append(pnl)
                stats_coin = by_coin[slot["coin"]]
                stats_coin["trades"] += 1
                stats_coin["wins"] += 1 if pnl > 0 else 0
                stats_coin["pnl"] += pnl
                stats_tf = by_timeframe[slot["timeframe"]]
                stats_tf["trades"] += 1
                stats_tf["wins"] += 1 if pnl > 0 else 0
                stats_tf["pnl"] += pnl
                stats_rg = by_regime[slot["regime"]]
                stats_rg["trades"] += 1
                stats_rg["wins"] += 1 if pnl > 0 else 0
                stats_rg["pnl"] += pnl
                del active_trades[market_id]

    # Force-close remaining open trades at final mark to avoid window-end bias.
    forced_closed = 0
    for market_id, slot in list(active_trades.items()):
        trade = slot["trade"]
        last_price = last_price_by_market.get(market_id)
        if last_price is None:
            continue
        pnl = trade.pnl_pct(last_price)
        pnl_total += pnl
        trades.append(pnl)
        stats_coin = by_coin[slot["coin"]]
        stats_coin["trades"] += 1
        stats_coin["wins"] += 1 if pnl > 0 else 0
        stats_coin["pnl"] += pnl
        stats_tf = by_timeframe[slot["timeframe"]]
        stats_tf["trades"] += 1
        stats_tf["wins"] += 1 if pnl > 0 else 0
        stats_tf["pnl"] += pnl
        stats_rg = by_regime[slot["regime"]]
        stats_rg["trades"] += 1
        stats_rg["wins"] += 1 if pnl > 0 else 0
        stats_rg["pnl"] += pnl
        forced_closed += 1
        del active_trades[market_id]

    print("\n" + "=" * 40)
    print(f"BACKTEST RESULTS ({PROFILE_NAME})")
    print("=" * 40)
    print(f"Closed PnL: {round(pnl_total, 4)}")
    print(f"Closed Trades: {len(trades)}")
    print(f"Forced Closes (EOD Mark): {forced_closed}")

    if trades:
        winrate = sum(1 for t in trades if t > 0) / len(trades)
        print(f"Win Rate (Closed): {round(winrate * 100, 2)}%")

    def print_breakdown(title, bucket):
        print(f"\n{title}")
        print("-" * len(title))
        if not bucket:
            print("(no trades)")
            return
        for key, s in sorted(bucket.items(), key=lambda kv: kv[1]["pnl"], reverse=True):
            n = s["trades"]
            wr = (s["wins"] / n * 100.0) if n else 0.0
            exp = (s["pnl"] / n) if n else 0.0
            print(
                f"{key:>8} | trades={n:4d} | win%={wr:5.1f} | pnl={s['pnl']:+.4f} | expectancy={exp:+.4f}"
            )

    print_breakdown("PER-COIN BREAKDOWN", by_coin)
    print_breakdown("PER-TIMEFRAME BREAKDOWN", by_timeframe)
    print_breakdown("PER-REGIME BREAKDOWN", by_regime)


if __name__ == "__main__":
    backtest()
