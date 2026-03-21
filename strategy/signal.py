def generate_signal(features):
    price = features["price"]
    momentum = features["momentum"]
    z_score = features["z_score"]
    rsi = features["rsi"]
    major_sma = features["major_sma"]
    oi_trend = features.get("oi_trend", 0)

    # --- STRATEGY 1: MOMENTUM BREAKOUT (YES) ---
    # Trend is up, z-score confirms breakout, RSI shows strength
    # OI Guard: Price increase must be backed by increasing or stable Open Interest
    if z_score > 1.5 and momentum > 0 and 55 < rsi < 85:
        if price > major_sma and price < 0.80:
            # We want to see OI not crashing (oi_trend >= -0.01)
            if oi_trend >= -0.01:
                return "BUY YES"

    # --- STRATEGY 2: MEAN REVERSION (YES) ---
    # Price crashed, z-score is very negative, RSI is oversold
    if z_score < -2.2 and rsi < 25:
        if price > 0.15:
            return "BUY YES"

    # --- STRATEGY 3: SELLING EXHAUSTION (NO) ---
    # Overbought conditions
    if price > 0.90 and rsi > 85 and price < features["sma"]:
        return "BUY NO"

    return None
