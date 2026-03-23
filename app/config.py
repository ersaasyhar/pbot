import json
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.getenv("BOT_CONFIG_PATH", os.path.join(BASE_DIR, "config.json"))


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {
            "bot": {"fetch_interval": 5, "top_k": 10, "active_coins": ["btc", "eth"]},
            "risk_profiles": {"SELECTED": "BALANCED"},
            "sizing_profiles": {"SELECTED": "FIXED"},
        }
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


_raw_config = load_config()

# --- Export constants ---
BOT_CONFIG = _raw_config.get("bot", {})
FETCH_INTERVAL = BOT_CONFIG.get("fetch_interval", 5)
TOP_K = BOT_CONFIG.get("top_k", 10)
ACTIVE_COINS = BOT_CONFIG.get(
    "active_coins", ["btc", "eth", "sol", "doge", "bnb", "xrp"]
)

# --- Export Profiles ---
RISK_PROFILES = _raw_config.get("risk_profiles", {})
SELECTED_RISK_PROFILE_NAME = RISK_PROFILES.get("SELECTED", "BALANCED")

SIZING_PROFILES = _raw_config.get("sizing_profiles", {})
SELECTED_SIZING_PROFILE_NAME = SIZING_PROFILES.get("SELECTED", "FIXED")
