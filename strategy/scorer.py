def compute_score(features):
    rsi = features["rsi"]

    # RSI Sweet Spot Bonus: 0.1 extra if RSI is between 40 and 70
    rsi_bonus = 0.1 if 40 < rsi < 70 else 0

    return (
        abs(features["momentum"]) * 0.5
        + features["volatility"] * 0.3
        + features["volume"] * 0.00001
        + rsi_bonus
    )
