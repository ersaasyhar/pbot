import numpy as np

def build_features(prices, volume):
    if len(prices) < 10: # Increased window for better stats
        return None

    prices_arr = np.array(prices)
    current_price = prices_arr[-1]
    
    # Basic Momentum
    momentum = current_price - prices_arr[0]
    
    # Volatility (Standard Deviation)
    volatility = np.std(prices_arr)
    
    # SMA (Fair Value proxy)
    sma = np.mean(prices_arr)
    
    # Z-Score (How many standard deviations from the mean)
    # This detects "Mispricing" / Overreactions
    if volatility > 0:
        z_score = (current_price - sma) / volatility
    else:
        z_score = 0

    return {
        "price": current_price,
        "momentum": momentum,
        "volatility": volatility,
        "sma": sma,
        "z_score": z_score,
        "volume": volume
    }