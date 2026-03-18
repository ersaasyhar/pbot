def compute_score(features):
    return (
        abs(features["momentum"]) * 0.6 +
        features["volatility"] * 0.3 +
        features["volume"] * 0.00001
    )