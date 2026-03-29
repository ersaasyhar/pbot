import math
import time

from core.strategy_utils import detect_regime, risk_profile_for_timeframe
from data.storage import (
    get_recent_oi,
    get_recent_prices,
    insert_market,
    insert_ws_ticks_bulk,
)
from features.builder import build_features
from strategy.paper_trader import execute_virtual_trade
from strategy.signal import generate_mean_reversion_signal, generate_trend_signal


class TradingPipeline:
    def __init__(self, runtime, logger, selected_risk_profile, sizing_profile_name):
        self.runtime = runtime
        self.logger = logger
        self.selected_risk_profile = selected_risk_profile
        self.sizing_profile_name = sizing_profile_name

    def queue_trade_candidate(self, candidate):
        market_id = candidate["market_id"]
        previous = self.runtime.entry_candidates.get(market_id)
        if (not previous) or candidate["decayed_ev"] > previous["decayed_ev"]:
            self.runtime.entry_candidates[market_id] = candidate

    def execute_top_candidates(self):
        if not self.runtime.entry_candidates:
            return

        now = int(time.time())
        max_entries = int(self.selected_risk_profile.get("max_entries_per_cycle", 3))
        max_age_sec = int(self.selected_risk_profile.get("max_signal_age_sec", 60))

        ranked = sorted(
            self.runtime.entry_candidates.values(),
            key=lambda x: x["decayed_ev"],
            reverse=True,
        )
        selected = 0
        for candidate in ranked:
            if selected >= max_entries:
                break
            if now - candidate["queued_at"] > max_age_sec:
                continue

            opened = execute_virtual_trade(
                candidate["market_id"],
                candidate["question"],
                candidate["side"],
                candidate["price"],
                candidate["coin"],
                candidate["timeframe"],
                self.sizing_profile_name,
                candidate["confidence"],
                effective_ev=candidate["decayed_ev"],
                regime=candidate["regime"],
                signal_age_sec=candidate["signal_age_sec"],
                end_time=candidate.get("end_time"),
                simulated_slippage_pct=candidate.get("simulated_slippage_pct"),
                max_slippage_abs=candidate.get("max_entry_slippage_abs"),
            )
            if opened:
                selected += 1

        self.runtime.entry_candidates.clear()

    def flush_ws_tick_buffer(self, force=False):
        if self.runtime.conn is None or not self.runtime.ws_tick_buffer:
            return
        if (
            not force
            and len(self.runtime.ws_tick_buffer) < self.runtime.ws_tick_flush_size
        ):
            return
        batch = self.runtime.ws_tick_buffer
        self.runtime.ws_tick_buffer = []
        try:
            insert_ws_ticks_bulk(self.runtime.conn, batch)
        except Exception as exc:
            self.logger.debug(f"WS tick flush failed: {exc}")

    def record_ws_tick(
        self,
        token_id,
        event_type,
        best_bid=None,
        best_ask=None,
        mid=None,
        spread=None,
        bid_sz_top5=None,
        ask_sz_top5=None,
        depth_top5=None,
        pressure=None,
        last_trade_price=None,
    ):
        if self.runtime.conn is None or not token_id:
            return
        market = self.runtime.active_markets.get(token_id, {})
        self.runtime.ws_tick_buffer.append(
            {
                "ts_ms": int(time.time() * 1000),
                "event_type": event_type,
                "token_id": token_id,
                "market_id": market.get("market_id"),
                "coin": market.get("coin"),
                "timeframe": market.get("timeframe"),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "spread": spread,
                "bid_sz_top5": bid_sz_top5,
                "ask_sz_top5": ask_sz_top5,
                "depth_top5": depth_top5,
                "pressure": pressure,
                "last_trade_price": last_trade_price,
            }
        )

    def _ingest_market_tick(
        self, token_id, price, spread=None, pressure=None, depth=None
    ):
        if self.runtime.conn is None:
            return None, None
        if not token_id or token_id not in self.runtime.active_markets:
            return None, None

        market = self.runtime.active_markets[token_id]
        market_id = market["market_id"]
        self.runtime.latest_prices[market_id] = price
        if spread is not None:
            self.runtime.latest_spreads[market_id] = spread
        if pressure is not None:
            self.runtime.latest_pressure[market_id] = pressure
        if depth is not None:
            self.runtime.latest_depth[market_id] = depth
        self.runtime.updates_count += 1
        return market, market_id

    def _should_persist_price(self, market_id, price):
        last_price = self.runtime.last_saved_price.get(market_id, 0)
        if abs(last_price - price) < 0.0001 and self.runtime.updates_count % 50 != 0:
            return False
        return True

    def _persist_market_price(self, market, market_id, price):
        market["price"] = price
        market["timestamp"] = int(time.time())
        insert_market(self.runtime.conn, market)
        self.runtime.last_saved_price[market_id] = price

    def _build_market_context(self, market):
        market_context = {
            "btc_trending_up": True,
            "btc_trending_down": True,
            "timeframe": market.get("timeframe", "5m"),
            "coin": market.get("coin", ""),
        }
        try:
            cursor = self.runtime.conn.cursor()
            cursor.execute(
                "SELECT price FROM market_prices WHERE coin='btc' AND timeframe='1h' ORDER BY timestamp DESC LIMIT 20"
            )
            btc_prices = [row[0] for row in cursor.fetchall()]
            if len(btc_prices) >= 10:
                btc_sma = sum(btc_prices) / len(btc_prices)
                cur_btc = btc_prices[0]
                market_context["btc_trending_up"] = cur_btc > btc_sma
                market_context["btc_trending_down"] = cur_btc < btc_sma
        except Exception as exc:
            self.logger.debug(f"BTC macro context fetch failed: {exc}")
        return market_context

    def _build_market_features(self, market, market_id):
        series = get_recent_prices(self.runtime.conn, market_id, limit=30)
        if len(series) < 20:
            return None

        oi_series = get_recent_oi(self.runtime.conn, market_id, limit=10)
        features = build_features(series, market.get("volume", 0), oi_series)
        if not features:
            return None

        cur_spread = self.runtime.latest_spreads.get(market_id, 0)
        cur_pressure = self.runtime.latest_pressure.get(market_id, 0.0)
        cur_depth = self.runtime.latest_depth.get(market_id, 0.0)
        features["current_spread"] = cur_spread
        features["pressure"] = cur_pressure
        features["depth_top5"] = cur_depth

        z_strength = min(abs(features.get("z_score", 0.0)) / 3.0, 1.0)
        ev_proxy = ((0.5 + (z_strength * 0.2)) * 0.10) - (
            (1.0 - (0.5 + (z_strength * 0.2))) * 0.05
        )
        self.logger.debug(
            f"ANALYSIS [{market['coin']}-{market['timeframe']}] | "
            f"P: {features['price']:.3f}, "
            f"Z: {features['z_score']:.2f}, "
            f"RSI: {features['rsi']:.1f}, "
            f"RelVol: {features['rel_vol']:.2f}, "
            f"Pressure: {cur_pressure:.2f}, "
            f"EVproxy: {ev_proxy:+.2f}"
        )
        return features, cur_spread, cur_pressure, cur_depth, z_strength

    def _entry_allowed_for_market(self, market):
        coin_key = (market.get("coin") or "").lower()
        if coin_key in self.runtime.blocked_coins:
            return False
        if (
            self.runtime.allowed_entry_coins
            and coin_key not in self.runtime.allowed_entry_coins
        ):
            return False
        if (
            self.runtime.allowed_entry_timeframes
            and market.get("timeframe") not in self.runtime.allowed_entry_timeframes
        ):
            return False
        return True

    def _compute_signal(self, features, market, market_context):
        timeframe = market.get("timeframe", "5m")
        regime = detect_regime(features, timeframe)
        market_context["regime"] = regime
        profile_tf = risk_profile_for_timeframe(self.selected_risk_profile, timeframe)

        if regime == "volatile":
            signal, confidence = None, 0.0
            strategy_name = "SKIP_VOLATILE"
        elif timeframe in ["1h", "4h"] or regime == "trend":
            signal, confidence = generate_trend_signal(
                features, profile_tf, market_context
            )
            strategy_name = "TREND"
        else:
            signal, confidence = generate_mean_reversion_signal(
                features, profile_tf, market_context
            )
            strategy_name = "REVERSION"
        return signal, confidence, strategy_name, regime, profile_tf

    def _is_price_in_no_trade_zone(self, yes_price, profile_tf):
        zone_min = float(profile_tf.get("no_trade_yes_min", 0.45))
        zone_max = float(profile_tf.get("no_trade_yes_max", 0.55))
        return zone_min <= float(yes_price) <= zone_max

    def _entry_displacement_and_momentum_ok(
        self, signal, yes_price, features, profile_tf
    ):
        min_disp = float(profile_tf.get("min_strike_displacement", 0.10))
        min_momo = float(profile_tf.get("entry_momentum_min_abs", 0.0))
        if abs(float(yes_price) - 0.5) < min_disp:
            return False
        momentum = float(features.get("momentum", 0.0))
        if signal == "BUY YES" and momentum < min_momo:
            return False
        if signal == "BUY NO" and momentum > -min_momo:
            return False
        return True

    def _passes_two_timeframe_confirmation(self, market, signal, profile_tf, now_ts):
        if not bool(profile_tf.get("require_multi_tf_confirmation", False)):
            return True
        required_tfs = [str(tf) for tf in profile_tf.get("confirmation_timeframes", [])]
        if not required_tfs:
            return True
        coin = (market.get("coin") or "").lower()
        max_age = int(profile_tf.get("confirmation_max_age_sec", 180))
        for tf in required_tfs:
            snap = self.runtime.latest_tf_signals.get((coin, tf))
            if not snap:
                return False
            if snap.get("side") != signal:
                return False
            if now_ts - int(snap.get("ts", now_ts)) > max_age:
                return False
        return True

    def _passes_hold_entry_filters(
        self, market, signal, yes_price, features, profile_tf
    ):
        if str(profile_tf.get("mode", "main")).lower() != "hold":
            return True

        now_ts = int(time.time())
        end_time = int(market.get("end_time") or 0)
        if end_time > 0:
            remaining = end_time - now_ts
            min_rem = int(profile_tf.get("hold_entry_min_remaining_sec", 30))
            max_rem = int(profile_tf.get("hold_entry_window_sec", 300))
            if remaining < min_rem or remaining > max_rem:
                return False

        pressure = float(features.get("pressure", 0.0))
        min_abs_pressure = float(profile_tf.get("hold_min_abs_pressure", 0.15))
        if abs(pressure) < min_abs_pressure:
            return False
        if signal == "BUY YES" and pressure <= 0:
            return False
        if signal == "BUY NO" and pressure >= 0:
            return False

        reversal_move = float(profile_tf.get("reversal_recent_move_pct", 0.05))
        reversal_band = float(profile_tf.get("reversal_strike_buffer", 0.08))
        near_strike = abs(float(yes_price) - 0.5) <= reversal_band
        if (
            near_strike
            and abs(float(features.get("recent_move_pct", 0.0))) >= reversal_move
        ):
            return False
        return True

    def _passes_external_context_filters(self, signal, profile_tf):
        if not bool(profile_tf.get("external_context_enabled", False)):
            return True

        spot = self.runtime.latest_external_spot or {}
        perp = self.runtime.latest_perp_context or {}
        if not spot or not perp:
            return False

        max_spread_bps = float(profile_tf.get("ext_max_spot_spread_bps", 4.0))
        spread_bps = float(spot.get("spread_bps") or 0.0)
        if spread_bps > max_spread_bps:
            return False

        min_spot_momentum = float(profile_tf.get("ext_min_spot_momentum_10s", 0.0))
        spot_momentum = float(spot.get("momentum_10s") or 0.0)
        if signal == "BUY YES" and spot_momentum < min_spot_momentum:
            return False
        if signal == "BUY NO" and spot_momentum > -min_spot_momentum:
            return False

        adverse_oi = float(profile_tf.get("ext_max_adverse_oi_delta_1m", 0.0))
        oi_delta = float(perp.get("oi_delta_1m") or 0.0)
        if adverse_oi > 0:
            if signal == "BUY YES" and oi_delta < -adverse_oi:
                return False
            if signal == "BUY NO" and oi_delta > adverse_oi:
                return False

        liq_adverse_ratio = float(profile_tf.get("ext_liq_adverse_ratio", 2.0))
        liq_long = float(perp.get("liq_long_1m") or 0.0)
        liq_short = float(perp.get("liq_short_1m") or 0.0)
        if signal == "BUY YES" and liq_long > (liq_short * liq_adverse_ratio):
            return False
        if signal == "BUY NO" and liq_short > (liq_long * liq_adverse_ratio):
            return False
        return True

    def _update_analysis_state(
        self,
        market_id,
        market,
        features,
        cur_pressure,
        cur_depth,
        z_strength,
        regime,
    ):
        base_confidence = 0.5 + (z_strength * 0.2)
        base_ev = (base_confidence * 0.10) - ((1.0 - base_confidence) * 0.05)
        self.runtime.latest_analysis[market_id] = {
            "timestamp": int(time.time()),
            "pressure": cur_pressure,
            "depth_top5": cur_depth,
            "z_score": features.get("z_score", 0.0),
            "momentum": features.get("momentum", 0.0),
            "effective_ev": base_ev,
            "regime": regime,
            "end_time": market.get("end_time"),
        }

    async def process_price_update(
        self, token_id, price, spread=None, pressure=None, depth=None
    ):
        market, market_id = self._ingest_market_tick(
            token_id, price, spread, pressure, depth
        )
        if not market:
            return

        if not self._should_persist_price(market_id, price):
            return

        self._persist_market_price(market, market_id, price)
        market_context = self._build_market_context(market)

        feature_bundle = self._build_market_features(market, market_id)
        if not feature_bundle:
            return
        features, cur_spread, cur_pressure, cur_depth, z_strength = feature_bundle

        if not self._entry_allowed_for_market(market):
            return

        signal, confidence, strategy_name, regime, profile_tf = self._compute_signal(
            features, market, market_context
        )
        self._update_analysis_state(
            market_id, market, features, cur_pressure, cur_depth, z_strength, regime
        )

        if not signal:
            self.runtime.signal_state.pop(market_id, None)
            return

        now = int(time.time())
        self.runtime.latest_tf_signals[
            ((market.get("coin") or "").lower(), market["timeframe"])
        ] = {
            "side": signal,
            "ts": now,
        }
        if self._is_price_in_no_trade_zone(price, profile_tf):
            return
        if not self._entry_displacement_and_momentum_ok(
            signal, price, features, profile_tf
        ):
            return
        if not self._passes_two_timeframe_confirmation(market, signal, profile_tf, now):
            return
        if not self._passes_hold_entry_filters(
            market, signal, price, features, profile_tf
        ):
            return
        if not self._passes_external_context_filters(signal, profile_tf):
            return

        tp_reward = 0.10
        sl_risk = 0.05
        raw_ev = (confidence * tp_reward) - ((1.0 - confidence) * sl_risk)

        max_allowed_spread = profile_tf.get("max_spread", 0.03)
        if cur_spread > max_allowed_spread:
            return

        min_depth = profile_tf.get("min_depth_top5", 200.0)
        if cur_depth > 0 and cur_depth < min_depth:
            return

        spread_cost = (cur_spread / max(price, 0.20)) * 0.5
        slippage_cost = 0.005
        effective_ev = raw_ev - spread_cost - slippage_cost
        min_effective_ev = profile_tf.get("min_effective_ev", 0.03)
        if effective_ev < min_effective_ev:
            return

        state = self.runtime.signal_state.get(market_id)
        if state and state.get("side") == signal:
            first_seen = state.get("first_seen", now)
        else:
            first_seen = now
            self.runtime.signal_state[market_id] = {
                "side": signal,
                "first_seen": first_seen,
            }

        signal_age_sec = max(0, now - first_seen)
        max_signal_age_sec = int(profile_tf.get("max_signal_age_sec", 60))
        if signal_age_sec > max_signal_age_sec:
            return

        decay_lambda = float(profile_tf.get("signal_decay_lambda", 0.02))
        decay = math.exp(-decay_lambda * signal_age_sec)
        decayed_ev = effective_ev * decay
        if decayed_ev < min_effective_ev:
            return

        end_time = market.get("end_time", 0)
        remaining = end_time - now
        if 0 < remaining < 120:
            return

        self.runtime.latest_analysis[market_id]["effective_ev"] = decayed_ev

        self.logger.info(
            f"✨ {strategy_name} SIGNAL: [{market['coin']}-{market['timeframe']}] {signal} "
            f"({int(confidence * 100)}%) | EV(raw/eff/decay): +{round(raw_ev * 100, 1)}%/+{round(effective_ev * 100, 1)}%/+{round(decayed_ev * 100, 1)}% "
            f"| Age={signal_age_sec}s | P={round(price, 4)} | Regime={regime}"
        )
        self.queue_trade_candidate(
            {
                "market_id": market_id,
                "question": market["question"],
                "side": signal,
                "price": price,
                "coin": market["coin"],
                "timeframe": market["timeframe"],
                "confidence": confidence,
                "regime": regime,
                "signal_age_sec": signal_age_sec,
                "decayed_ev": decayed_ev,
                "end_time": market.get("end_time"),
                "simulated_slippage_pct": profile_tf.get("simulated_slippage_pct"),
                "max_entry_slippage_abs": profile_tf.get("max_entry_slippage_abs"),
                "queued_at": now,
            }
        )
