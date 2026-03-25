import unittest

from core.strategy_utils import (
    compute_coin_gate,
    detect_regime,
    risk_profile_for_timeframe,
)


class StrategyUtilsTest(unittest.TestCase):
    def test_risk_profile_for_timeframe_without_override(self):
        profile = {"tp_pct": 0.12, "sl_pct": 0.05}
        merged = risk_profile_for_timeframe(profile, "15m")
        self.assertEqual(merged["tp_pct"], 0.12)
        self.assertEqual(merged["sl_pct"], 0.05)

    def test_risk_profile_for_timeframe_with_override(self):
        profile = {
            "tp_pct": 0.12,
            "sl_pct": 0.05,
            "timeframe_overrides": {"15m": {"sl_pct": 0.07}},
        }
        merged = risk_profile_for_timeframe(profile, "15m")
        self.assertEqual(merged["tp_pct"], 0.12)
        self.assertEqual(merged["sl_pct"], 0.07)

    def test_detect_regime_volatile(self):
        features = {"rel_vol": 2.0, "momentum_pct": 0.0, "z_score": 0.0}
        self.assertEqual(detect_regime(features, "15m"), "volatile")

    def test_detect_regime_trend_hourly(self):
        features = {"rel_vol": 1.0, "momentum_pct": 0.03, "z_score": 0.1}
        self.assertEqual(detect_regime(features, "1h"), "trend")

    def test_compute_coin_gate_disabled(self):
        profile = {"coin_gate_enabled": False}
        blocked, stats = compute_coin_gate(profile, history=[])
        self.assertEqual(blocked, {})
        self.assertEqual(stats, {})

    def test_compute_coin_gate_or_blocks_weak_coin(self):
        profile = {
            "coin_gate_enabled": True,
            "coin_gate_min_closed_trades": 3,
            "coin_gate_lookback_trades": 5,
            "coin_gate_min_win_rate": 0.5,
            "coin_gate_max_expectancy": -0.01,
            "coin_gate_logic": "or",
            "trade_allowed_coins": ["btc", "eth"],
        }
        history = [
            {"coin": "btc", "pnl": -1.0},
            {"coin": "btc", "pnl": -0.5},
            {"coin": "btc", "pnl": 0.2},
            {"coin": "eth", "pnl": 0.6},
            {"coin": "eth", "pnl": 0.5},
            {"coin": "eth", "pnl": 0.4},
        ]
        blocked, _ = compute_coin_gate(profile, history)
        self.assertIn("btc", blocked)
        self.assertNotIn("eth", blocked)

    def test_compute_coin_gate_deadlock_guard(self):
        profile = {
            "coin_gate_enabled": True,
            "coin_gate_min_closed_trades": 2,
            "coin_gate_lookback_trades": 3,
            "coin_gate_min_win_rate": 0.9,
            "coin_gate_max_expectancy": 0.5,
            "coin_gate_logic": "or",
            "trade_allowed_coins": ["btc"],
        }
        history = [
            {"coin": "btc", "pnl": -0.2},
            {"coin": "btc", "pnl": -0.1},
        ]
        blocked, stats = compute_coin_gate(profile, history)
        self.assertEqual(blocked, {})
        self.assertIn("btc", stats)


if __name__ == "__main__":
    unittest.main()
