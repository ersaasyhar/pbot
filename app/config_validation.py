def _require_dict(parent, key):
    val = parent.get(key)
    if not isinstance(val, dict):
        raise ValueError(f"config.{key} must be an object")
    return val


def _require_key(parent, key, where):
    if key not in parent:
        raise ValueError(f"{where}.{key} is required")


def validate_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError("config root must be an object")

    risk_profiles = _require_dict(cfg, "risk_profiles")
    sizing_profiles = _require_dict(cfg, "sizing_profiles")

    _require_key(risk_profiles, "SELECTED", "config.risk_profiles")
    _require_key(sizing_profiles, "SELECTED", "config.sizing_profiles")

    selected_risk = risk_profiles.get("SELECTED")
    selected_sizing = sizing_profiles.get("SELECTED")
    if selected_risk not in risk_profiles:
        raise ValueError(
            f"config.risk_profiles.SELECTED='{selected_risk}' is not defined"
        )
    if selected_sizing not in sizing_profiles:
        raise ValueError(
            f"config.sizing_profiles.SELECTED='{selected_sizing}' is not defined"
        )

    selected_profile = risk_profiles[selected_risk]
    if not isinstance(selected_profile, dict):
        raise ValueError(f"config.risk_profiles.{selected_risk} must be an object")
    required_numeric = [
        "tp_pct",
        "sl_pct",
        "min_effective_ev",
        "max_signal_age_sec",
        "max_entries_per_cycle",
    ]
    for key in required_numeric:
        _require_key(selected_profile, key, f"config.risk_profiles.{selected_risk}")

    selected_sizing_profile = sizing_profiles[selected_sizing]
    if not isinstance(selected_sizing_profile, dict):
        raise ValueError(f"config.sizing_profiles.{selected_sizing} must be an object")
    _require_key(
        selected_sizing_profile, "type", f"config.sizing_profiles.{selected_sizing}"
    )
    _require_key(
        selected_sizing_profile, "value", f"config.sizing_profiles.{selected_sizing}"
    )

    return cfg
