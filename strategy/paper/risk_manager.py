from app.config import RISK_PROFILES, SELECTED_RISK_PROFILE_NAME, SIZING_PROFILES


def calculate_stake(portfolio, sizing_profile_name, confidence=1.0):
    profile = SIZING_PROFILES.get(sizing_profile_name, SIZING_PROFILES.get("FIXED"))
    base_value = 0
    if profile["type"] == "fixed":
        base_value = float(profile["value"])
    else:
        base_value = round(portfolio["balance"] * profile["value"], 2)

    high_water = portfolio.get("high_water_mark", 1000.0)
    current_bal = portfolio["balance"]

    drawdown_pct = 0.0
    if high_water > 0 and current_bal < high_water:
        drawdown_pct = (high_water - current_bal) / high_water

    drawdown_penalty = 1.0
    if drawdown_pct >= 0.10:
        drawdown_penalty = 0.20
    elif drawdown_pct >= 0.05:
        drawdown_penalty = 0.50
    elif drawdown_pct >= 0.02:
        drawdown_penalty = 0.80

    return round(base_value * confidence * drawdown_penalty, 2)


def risk_profile_for_timeframe(timeframe):
    base = RISK_PROFILES.get(SELECTED_RISK_PROFILE_NAME, {}) or {}
    overrides = (base.get("timeframe_overrides", {}) or {}).get(timeframe, {}) or {}
    if not overrides:
        return base
    merged = dict(base)
    merged.update(overrides)
    return merged
