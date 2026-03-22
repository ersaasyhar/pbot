def generate_signal(features, profile, market_context=None):
    """
    Generates a signal based on the provided risk profile.
    v22: MACRO ALIGNMENT
    - Safety Zone (0.20 - 0.80)
    - Bitcoin Trend Filter (Optional but recommended)
    - Consistent thresholds
    """
    price = features["price"]
    momentum = features["momentum"]
    z_score = features["z_score"]
    rsi = features["rsi"]
    major_sma = features["major_sma"]
    oi_trend = features.get("oi_trend", 0)
    
    # --- MACRO CONTEXT ---
    btc_up = True
    btc_down = True
    if market_context:
        btc_up = market_context.get("btc_trending_up", True)
        btc_down = market_context.get("btc_trending_down", True)

    # --- STRICT SAFETY ZONE ---
    if price < 0.20 or price > 0.80:
        return None

    # Thresholds from Profile
    z_thresh = profile.get("z_score_threshold", 1.2)
    rsi_min = profile.get("rsi_min", 45)
    rsi_max = profile.get("rsi_max", 85)
    oi_min = profile.get("min_oi_trend", -0.02)

    # --- STRATEGY 1: BREAKOUT (BUY YES) ---
    if z_score > z_thresh and momentum > 0 and btc_up:
        if rsi_min < rsi < rsi_max:
            if price > major_sma and oi_trend >= oi_min:
                return "BUY YES"

    # --- STRATEGY 2: BREAKOUT (BUY NO) ---
    if z_score < -z_thresh and momentum < 0 and btc_down:
        no_rsi = 100 - rsi
        if rsi_min < no_rsi < rsi_max:
            if price < major_sma and oi_trend >= oi_min:
                return "BUY NO"

    # --- STRATEGY 3: MEAN REVERSION (FADE) ---
    if z_score < -2.5 and rsi < 20 and btc_up:
        return "BUY YES"
    
    if z_score > 2.5 and rsi > 80 and btc_down:
        return "BUY NO"

    return None
