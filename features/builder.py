import numpy as np


def build_features(prices, volume, oi_series=None):
    if len(prices) < 10:  # Minimum window for stats
        return None

    prices_arr = np.array(prices)
    current_price = prices_arr[-1]

    # --- TREND ---
    momentum = current_price - prices_arr[0]
    momentum_pct = momentum / max(current_price, 0.01)

    # Simple Moving Average
    sma = np.mean(prices_arr)

    # --- VOLATILITY ---
    volatility = np.std(prices_arr)

    # Volatility Regime (v27)
    # Compare last 5 points vol to the full window vol
    short_vol = np.std(prices_arr[-5:]) if len(prices_arr) >= 5 else volatility
    rel_vol = short_vol / volatility if volatility > 0 else 1.0

    # Z-Score
    if volatility > 0:
        z_score = (current_price - sma) / volatility
    else:
        z_score = 0

    # --- RSI ---
    deltas = np.diff(prices_arr)
    gain = np.mean(deltas[deltas > 0]) if any(deltas > 0) else 0
    loss = abs(np.mean(deltas[deltas < 0])) if any(deltas < 0) else 0

    if loss == 0:
        rsi = 100
    else:
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

    # Major Trend (20 periods)
    if len(prices) >= 20:
        major_sma = np.mean(prices_arr[-20:])
    else:
        major_sma = sma

    # --- OPEN INTEREST TREND ---
    oi_trend = 0
    if oi_series and len(oi_series) >= 5:
        # Calculate percentage change in OI over the available window
        if oi_series[0] > 0:
            oi_trend = (oi_series[-1] - oi_series[0]) / oi_series[0]
        else:
            oi_trend = 0

    # Recent move helps avoid chasing already-exhausted breakouts.
    recent_move_pct = 0.0
    if len(prices_arr) >= 4:
        base = max(prices_arr[-4], 0.01)
        recent_move_pct = abs((prices_arr[-1] - prices_arr[-4]) / base)

    return {
        "price": current_price,
        "momentum": momentum,
        "momentum_pct": momentum_pct,
        "volatility": volatility,
        "rel_vol": rel_vol,
        "sma": sma,
        "major_sma": major_sma,
        "z_score": z_score,
        "rsi": rsi,
        "volume": volume,
        "oi_trend": oi_trend,
        "recent_move_pct": recent_move_pct,
    }
