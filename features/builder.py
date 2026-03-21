import numpy as np

def build_features(prices, volume, oi_series=None):
    if len(prices) < 10: # Minimum window for stats
        return None

    prices_arr = np.array(prices)
    current_price = prices_arr[-1]
    
    # --- TREND ---
    momentum = current_price - prices_arr[0]
    
    # Simple Moving Average
    sma = np.mean(prices_arr)
    
    # --- VOLATILITY ---
    volatility = np.std(prices_arr)
    
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

    return {
        "price": current_price,
        "momentum": momentum,
        "volatility": volatility,
        "sma": sma,
        "major_sma": major_sma,
        "z_score": z_score,
        "rsi": rsi,
        "volume": volume,
        "oi_trend": oi_trend
    }
