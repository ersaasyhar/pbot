def detect_regime(features, timeframe, volatile_threshold=1.8):
    rel_vol = features.get("rel_vol", 1.0)
    momentum_pct = abs(features.get("momentum_pct", 0.0))
    z_abs = abs(features.get("z_score", 0.0))
    if rel_vol >= float(volatile_threshold):
        return "volatile"
    if timeframe in ["1h", "4h"]:
        return "trend" if z_abs >= 0.8 or momentum_pct >= 0.02 else "range"
    return "trend" if z_abs >= 1.5 or momentum_pct >= 0.03 else "range"


def profile_for_timeframe(profile, timeframe):
    base = profile or {}
    overrides = (base.get("timeframe_overrides", {}) or {}).get(timeframe, {}) or {}
    if not overrides:
        return base
    merged = dict(base)
    merged.update(overrides)
    return merged
