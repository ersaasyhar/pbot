def generate_signal(features):
    price = features["price"]
    momentum = features["momentum"]
    volatility = features["volatility"]
    z_score = features["z_score"]

    # --- REFINED STRATEGY 1: DYNAMIC MOMENTUM BREAKOUT ---
    # Instead of a fixed 0.05, we look for moves that are 2 standard deviations away
    # and confirm with positive momentum.
    if z_score > 2.0 and momentum > 0:
        # Avoid buying things that are already extremely "Yes" (low profit potential)
        if price < 0.85:
            return "BUY YES"

    # --- REFINED STRATEGY 2: MEAN REVERSION (MISPRICING) ---
    # If a price crashes hard (Z-score < -2.5) but the market is still liquid,
    # it might be an overreaction.
    if z_score < -2.5:
        # Buy the dip (Mean reversion play)
        if price > 0.10:
            return "BUY YES"

    # --- REFINED STRATEGY 3: SELLING STRENGTH ---
    # If it's over-extended at the top, might be a good time to sell or "Buy NO"
    if z_score > 2.5 and price > 0.90:
        return "BUY NO"

    return None