# --- RISK PROFILES ---
RISK_PROFILES = {
    "CONSERVATIVE": {
        "z_score_threshold": 1.5,
        "rsi_min": 55,
        "rsi_max": 85,
        "max_spread": 0.03,
        "min_oi_trend": -0.01,
        "min_volume": 2000
    },
    "BALANCED": {
        "z_score_threshold": 1.2,
        "rsi_min": 45,
        "rsi_max": 85,
        "max_spread": 0.05,
        "min_oi_trend": -0.02,
        "min_volume": 500
    },
    "AGGRESSIVE": {
        "z_score_threshold": 0.8,
        "rsi_min": 35,
        "rsi_max": 90,
        "max_spread": 0.08,
        "min_oi_trend": -0.05,
        "min_volume": 100
    }
}

# --- TRADE SIZING PROFILES ---
SIZING_PROFILES = {
    "FIXED": {
        "type": "fixed",
        "value": 100.0  # $100 per trade
    },
    "PERCENTAGE": {
        "type": "percentage",
        "value": 0.05   # 5% of total portfolio balance
    }
}
