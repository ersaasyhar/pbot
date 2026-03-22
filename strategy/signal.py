# Renamed from generate_signal
def generate_trend_signal(features, profile, market_context=None):
    """
    v25-v30: DEEP VALUE SNIPER (TREND FOLLOWING)
    - Looks for high-momentum breakouts on stable trends.
    - Best suited for 1h/4h charts.
    """
    price = features["price"]  # This is the YES price
    momentum = features["momentum"]
    z_score = features["z_score"]
    rsi = features["rsi"]
    major_sma = features["major_sma"]
    oi_trend = features.get("oi_trend", 0)
    pressure = features.get("pressure", 0)
    recent_move_pct = features.get("recent_move_pct", 0.0)

    # --- MACRO CONTEXT ---
    btc_up = True
    btc_down = True
    timeframe = "5m"
    if market_context:
        btc_up = market_context.get("btc_trending_up", True)
        btc_down = market_context.get("btc_trending_down", True)
        timeframe = market_context.get("timeframe", "5m")

    # Thresholds from Profile
    z_thresh = profile.get("z_score_threshold", 1.2)
    rsi_min = profile.get("rsi_min", 45)
    rsi_max = profile.get("rsi_max", 85)
    oi_min = profile.get("min_oi_trend", -0.02)
    max_recent_move_pct = profile.get("max_recent_move_pct", 0.06)

    # --- VOLATILITY REGIME & TIMEFRAME ADJUSTMENT ---
    rel_vol = features.get("rel_vol", 1.0)
    vol_multiplier = max(1.0, min(rel_vol, 2.0))
    z_thresh *= vol_multiplier

    if timeframe in ["1h", "4h"]:
        z_thresh *= 0.8
    else:
        z_thresh *= 1.2

    signal = None
    confidence = 0.0

    def calc_confidence(z, p, oi):
        z_norm = min(abs(z) / (z_thresh * 3), 1.0) * 0.2
        p_norm = min(abs(p) / 0.8, 1.0) * 0.2
        oi_norm = min(max(oi, 0) / 0.1, 1.0) * 0.1
        return round(0.5 + z_norm + p_norm + oi_norm, 2)

    # --- STRATEGY 1: TREND BREAKOUT (BUY YES) ---
    if 0.20 <= price <= 0.45:
        if z_score > z_thresh and momentum > 0 and btc_up:
            if rsi_min < rsi < rsi_max:
                if pressure > 0.15:
                    if (
                        price > major_sma
                        and oi_trend >= oi_min
                        and recent_move_pct <= max_recent_move_pct
                    ):
                        signal = "BUY YES"
                        confidence = calc_confidence(z_score, pressure, oi_trend)

    # --- STRATEGY 2: TREND BREAKOUT (BUY NO) ---
    no_price = round(1.0 - price, 4)
    if 0.20 <= no_price <= 0.45:
        if z_score < -z_thresh and momentum < 0 and btc_down:
            no_rsi = 100 - rsi
            if rsi_min < no_rsi < rsi_max:
                if pressure < -0.15:
                    if (
                        price < major_sma
                        and oi_trend >= oi_min
                        and recent_move_pct <= max_recent_move_pct
                    ):
                        signal = "BUY NO"
                        confidence = calc_confidence(z_score, pressure, oi_trend)

    if signal:
        return signal, confidence
    return None, 0.0


def generate_mean_reversion_signal(features, profile, market_context=None):
    """
    v31: MEAN REVERSION STRATEGY
    - Bets against extreme, short-term price spikes.
    - Best suited for 5m/15m charts.
    """
    price = features["price"]
    z_score = features["z_score"]
    rsi = features["rsi"]

    # --- MACRO CONTEXT ---
    btc_up = True
    btc_down = True
    if market_context:
        btc_up = market_context.get("btc_trending_up", True)
        btc_down = market_context.get("btc_trending_down", True)

    # This strategy looks for overreactions, so it doesn't use the deep value price filter.
    # It still respects the absolute safety zone (0.20-0.80).
    if price < 0.20 or price > 0.80:
        return None, 0.0

    signal = None
    confidence = 0.0

    def calc_confidence(z):
        # Confidence is based on how extreme the z-score is.
        # A z-score of 4.0 is much stronger than 2.5.
        z_norm = min((abs(z) - 2.5) / 2.0, 1.0)  # Scale from 2.5 to 4.5
        return round(0.5 + (z_norm * 0.5), 2)

    # --- STRATEGY: FADE THE SPIKE ---
    # If price spikes (high Z-score, high RSI) and BTC isn't in a strong uptrend, bet against it.
    if z_score > 2.5 and rsi > 80 and not btc_up:
        signal = "BUY NO"
        confidence = calc_confidence(z_score)

    # If price crashes (low Z-score, low RSI) and BTC isn't in a strong downtrend, bet on recovery.
    if z_score < -2.5 and rsi < 20 and not btc_down:
        signal = "BUY YES"
        confidence = calc_confidence(z_score)

    if signal:
        return signal, confidence
    return None, 0.0
