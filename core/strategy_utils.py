def compute_coin_gate(profile, history):
    """
    Build blocked-coin set from rolling paper-trade performance.
    Default behavior is strict OR gating: block coin if win-rate or expectancy is weak.
    """
    if not bool(profile.get("coin_gate_enabled", True)):
        return {}, {}
    if not history:
        return {}, {}

    min_trades = int(profile.get("coin_gate_min_closed_trades", 12))
    lookback = int(profile.get("coin_gate_lookback_trades", 30))
    min_win_rate = float(profile.get("coin_gate_min_win_rate", 0.35))
    max_expectancy = float(profile.get("coin_gate_max_expectancy", 0.0))
    logic_mode = str(profile.get("coin_gate_logic", "or")).lower()

    grouped = {}
    for t in history:
        coin = (t.get("coin") or "").lower()
        if not coin:
            continue
        grouped.setdefault(coin, []).append(t)

    blocked = {}
    debug_stats = {}
    for coin, trades in grouped.items():
        sample = trades[-lookback:]
        n = len(sample)
        if n < min_trades:
            continue
        pnl_values = [float(t.get("pnl", 0.0)) for t in sample]
        wins = sum(1 for p in pnl_values if p > 0)
        win_rate = wins / n if n > 0 else 0.0
        expectancy = (sum(pnl_values) / n) if n > 0 else 0.0
        debug_stats[coin] = {
            "trades": n,
            "win_rate": round(win_rate * 100, 1),
            "expectancy": round(expectancy, 4),
        }
        if logic_mode == "and":
            should_block = expectancy <= max_expectancy and win_rate <= min_win_rate
        else:
            should_block = expectancy <= max_expectancy or win_rate <= min_win_rate
        if should_block:
            blocked[coin] = debug_stats[coin]

    # Deadlock guard: never block the entire configured entry universe.
    allowed = set([str(c).lower() for c in profile.get("trade_allowed_coins", [])])
    if allowed and blocked and allowed.issubset(set(blocked.keys())):
        return {}, debug_stats

    return blocked, debug_stats


def detect_regime(features, timeframe):
    rel_vol = features.get("rel_vol", 1.0)
    momentum_pct = abs(features.get("momentum_pct", 0.0))
    z_abs = abs(features.get("z_score", 0.0))

    # Raise volatile threshold so we do not over-classify short noise bursts as "skip".
    if rel_vol >= 1.8:
        return "volatile"

    if timeframe in ["1h", "4h"]:
        return "trend" if z_abs >= 0.8 or momentum_pct >= 0.02 else "range"

    return "trend" if z_abs >= 1.5 or momentum_pct >= 0.03 else "range"


def risk_profile_for_timeframe(base_profile, timeframe):
    base = base_profile or {}
    overrides = (base.get("timeframe_overrides", {}) or {}).get(timeframe, {}) or {}
    if not overrides:
        return base
    merged = dict(base)
    merged.update(overrides)
    return merged
