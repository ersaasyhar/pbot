def generate_signal(features, profile):
    """
    Generates a signal based on the provided risk profile.
    profile: dict from app.profiles.RISK_PROFILES
    """
    price = features["price"]
    momentum = features["momentum"]
    z_score = features["z_score"]
    rsi = features["rsi"]
    major_sma = features["major_sma"]
    oi_trend = features.get("oi_trend", 0)
    
    # Extract profile thresholds
    z_thresh = profile.get("z_score_threshold", 1.5)
    rsi_min = profile.get("rsi_min", 55)
    rsi_max = profile.get("rsi_max", 85)
    oi_min = profile.get("min_oi_trend", -0.01)

    # --- STRATEGY 1: MOMENTUM BREAKOUT (YES) ---
    if z_score > z_thresh and momentum > 0:
        if rsi_min < rsi < rsi_max:
            if price > major_sma and price < 0.85:
                if oi_trend >= oi_min:
                    return "BUY YES"

    # --- STRATEGY 2: MEAN REVERSION (YES) ---
    # Be slightly more aggressive on mean reversion in AGGRESSIVE mode
    mr_z_thresh = -z_thresh - 0.5
    if z_score < mr_z_thresh and rsi < (rsi_min - 20):
        if price > 0.10:
            return "BUY YES"

    # --- STRATEGY 3: SELLING EXHAUSTION (NO) ---
    if price > 0.85 and rsi > rsi_max and price < features["sma"]:
        return "BUY NO"

    return None
