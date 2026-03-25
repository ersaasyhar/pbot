# 🤖 Polymarket Trading Bot: Project Guide

This project is a professional high-frequency trading bot designed for Polymarket crypto "Up/Down" events. It features a real-time WebSocket streamer, a symmetric signal engine, and a secure analytics terminal.

📜 **Development Evolution**
*   **v1-19:** Foundational REST/WebSocket polling and basic safety guards.
*   **v20 "Precision Guard":** Symmetric YES/NO logic and percentage-based exits.
*   **v21-v29 "The Quant Stack":** A full suite of institutional-grade features transforming the bot from a simple signal-follower to a professional probabilistic trading system.
*   **v32 "Profitability Upgrade":** Regime-aware routing fixes, friction-adjusted EV, liquidity gating, fresh-breakout protection, early exits, and SQLite lock hardening.
*   **v33 "Selectivity Engine":** Signal time-decay, top-N trade competition, and new performance metrics (expectancy/regime/entry-age/exit-reason).
*   **v35 "Runtime Stability":** Stable yes-side mapping, active-market routing fixes, book-snapshot guards, and ordered tick reads.
*   **v36 "Execution Safety":** Automatic coin gate, stale-position timeout close, profile-based TP/SL, and per-coin dashboard analytics.
*   **v39 "Replay Data Pipeline":** WS tick recorder (`ws_ticks`), SQL paper-trade mirror (`paper_trades`), replay backtest, and walk-forward validation.
*   **v40 "SQLite Portfolio Core":** Paper portfolio migrated from JSON to SQLite source-of-truth with deadlock-safe coin gate.

---

### 🏛️ The Quant Stack (v29)
The bot now operates on a professional architecture that mirrors institutional trading systems, focusing on mathematical edge and risk management.

*   **Layer 1: Market Data (Deep Depth)**
    *   The bot analyzes the **Top 5 levels** of the order book to detect "hidden walls" of buy/sell pressure, providing a true sense of **Order Book Imbalance (OBI)**.

*   **Layer 2: Feature Engineering (Volatility Regimes)**
    *   It detects the market's "Volatility Regime" by comparing short-term vs. long-term price variance.
    *   During chaotic periods, the bot automatically **increases its standards**, requiring stronger signals to trade.

*   **Layer 3: Strategy Engine (The Multi-Strategy Core)**
    *   **Strategy Router (v31):** The bot now intelligently selects the optimal strategy based on market timeframe:
        *   **Current live focus:** `BTC 15m` trend-following only.
        *   **Research result:** `BTC 5m` was negative in sweep testing and is currently disabled for live trading.
    *   **Bitcoin Macro Trend Filter:** The bot aligns its BUY/SELL decisions with the overall Bitcoin trend, only taking `BUY YES` trades when BTC is trending up, and `BUY NO` trades when BTC is trending down.
    *   **Signal → Probability:** Signals are converted into a **Confidence Score** (0.5 to 1.0) based on Z-Score, OBI, and Open Interest alignment.
    *   **Probability → Expected Value (EV):** The bot will **reject any trade** that doesn't have a positive mathematical edge, calculated as: `EV = (Win % * Reward) - (Loss % * Risk)`.

*   **Layer 4: Execution (Realistic Simulation)**
    *   A **0.5% slippage penalty** is applied to all paper trades to simulate the real-world cost of crossing the bid-ask spread.

*   **Layer 5: Risk Engine (Capital Preservation)**
    *   **Circuit Breaker:** Automatically halts all new trading for 24 hours if the portfolio loses more than **$50 (5% of capital)** in a day.
    *   **Correlation Guard:** Prevents over-exposure by limiting active trades to 1 per coin and 3 per side (e.g., max 3 `BUY NO` trades at once).

*   **Layer 6: Portfolio Engine (Dynamic Sizing)**
    *   Instead of a fixed $10 bet, the bot **scales its position size** based on the Confidence Score. Stronger signals get more capital.

### 🛠 Tools & Technologies
- **Language:** Python 3.12+ (uv manager)
- **Web Engine:** Flask (Secure Terminal UI + Tailwind CSS)
- **Networking:** `websockets` (Real-time CLOB market stream)
- **Database:** SQLite (`market_prices`, `ws_ticks`, `paper_trades`, `paper_portfolio_state`)
- **APIs:** Gamma (Discovery), CLOB (Execution), Data (Conviction)

### 📂 Directory Structure
- **`config.json`**: **Master Control.** Current runtime uses a single `MAIN` profile and sizing profile.
- **`app/`**: Dashboard API, UI Templates, and Config Loader.
- **`core/`**: The high-speed async engine (WebSocket handler).
- **`strategy/`**: Symmetric Signal logic and Paper Trading module.
- **`features/`**: Real-time indicator building (RSI, Z-Score, Trend).
- **`db/`**: Price history, trade history, and PID management.

### 🚀 Quick Start
1.  **Configure**: Fill in `.env` (API Keys) and `config.json` (MAIN profile + sizing).
2.  **Run Bot**: `make run`
3.  **Start Dashboard**: `make dashboard`
4.  **Terminal**: Visit `http://<your-server-ip>/` (Nginx reverse proxy) or `http://<your-server-ip>:5000` (direct Flask) and log in with `DASHBOARD_PASSWORD` from `.env`.

### 📈 Maintenance & Commands
- **Check Status**: `make status`
- **Reset Portfolio**: `make reset-portfolio` (Wipes history and returns balance to $1,000)
- **Backtest**: `make backtest` (Matched to your current `config.json` profile)
- **Replay Backtest**: `make replay` (Uses recorded `ws_ticks` + friction model)
- **Walk-Forward**: `make walkforward` (Train/validate over rolling replay windows)
- **Watch Logs**: `make logs`

### 🧰 Runtime Modes (`nohup` vs `systemd`)

This project supports both modes:

*   **`systemd` (recommended for servers):**
    *   Auto-restart on crash, boot persistence, and centralized logs (`journalctl`).
    *   Service names used by this project:
        *   `pbot-bot.service`
        *   `pbot-dashboard.service`
    *   Typical commands:
        *   `sudo systemctl status pbot-bot pbot-dashboard nginx`
        *   `sudo systemctl restart pbot-bot pbot-dashboard nginx`
        *   `sudo journalctl -u pbot-bot -f`
*   **`nohup` (legacy/dev fallback):**
    *   Used when `systemd` services are not installed.
    *   Process/log tracking is PID-file based (`db/*.pid`, `collector.log`, `dashboard.log`).

`Makefile` is systemd-aware: if services exist, `make run`, `make dashboard`, `make stop`, `make dashboard-stop`, `make status`, and `make logs` use systemd; otherwise they fall back to legacy `nohup` behavior.

---

### 🆕 v32 Profitability Upgrade (Current)

The current implementation adds practical "edge protection" layers focused on reducing bad entries and making simulation closer to live behavior:

*   **Regime-Aware Strategy Routing (Fixed):**
    *   The engine now routes using actual market timeframe and detected regime (`trend`, `range`, `volatile`) instead of defaulting to a fallback context.
*   **Fresh Breakout Guard:**
    *   Trend entries are rejected if the move is already too extended (`max_recent_move_pct` in `config.json`).
*   **Execution Friction EV:**
    *   Entry now uses `effective_ev = raw_ev - spread_cost - slippage_cost`.
    *   Trades must pass `min_effective_ev` (profile-based).
*   **Liquidity Gate:**
    *   Uses top-5 order book depth (`min_depth_top5`) to avoid thin books.
*   **Lifecycle Upgrades:**
    *   Early exits trigger on EV flip, pressure flip, and max hold-time per timeframe.
*   **SQLite Concurrency Hardening:**
    *   WAL mode + busy timeout + commit-per-write added to reduce lock failures.
*   **Backtest Compatibility Fixes:**
    *   Backtest now uses the same strategy router and context proxies (macro + pressure proxy) so it can produce realistic non-zero trade flow.

### 🆕 v33 Selectivity Engine

This version focuses on aggressive rejection of weak trades:

*   **Signal Time Decay:**
    *   Signals decay by age using `exp(-lambda * age)` and are ignored after `max_signal_age_sec`.
*   **Top-N Execution Per Cycle:**
    *   Valid candidates are ranked by decayed EV.
    *   Only best `max_entries_per_cycle` are executed each sync cycle.
*   **Metrics Added to Dashboard API:**
    *   `expectancy`, `avg_signal_age_sec`, `regime_pnl`, `exit_reasons`.
*   **Trade Metadata Enriched:**
    *   Saved fields include `signal_age_sec`, `hold_seconds`, and `exit_reason`.

### 🆕 v34 Fast Calibration (Sweep + Safe Auto-Apply)

This version adds fast parameter-search tooling so strategy logic can be evaluated in minutes instead of waiting days:

*   **Batch Sweep Tool (`backtest.sweep`):**
    *   Sweeps `min_effective_ev`, `signal_decay_lambda`, `max_signal_age_sec`, and `max_entries_per_cycle`.
    *   Ranks parameter sets by score/expectancy/profit factor/trade count.
*   **Best Params Export:**
    *   Saves results to `db/best_params.json`.
*   **Safe Config Auto-Apply:**
    *   `--apply-best` updates the selected profile in `config.json`.
    *   Guarded by `--min-closed-for-apply` (default `30`) to avoid tuning from tiny samples.

---

### 🔍 Debugging & Deep Analysis (v30)

The bot is designed to be highly selective, only taking trades that meet its stringent "institutional-grade" filters. To understand exactly why (or why not) a trade is being considered, you can use the debug logs.

**1. Accessing Debug Logs:**
*   Debug logging is **always active** on your bot instance.
*   All detailed analysis logs and system output are consolidated into a single file: `collector.log`.
*   To view the live stream of these logs, run: `make logs`

**2. Understanding `ANALYSIS` Messages:**
The log will show `ANALYSIS` messages for every market that the bot evaluates. Each message contains crucial metrics:

```
DEBUG | ANALYSIS [COIN-TIMEFRAME] | P: PRICE, Z: Z-SCORE, RSI: RSI, RelVol: REL_VOL, Pressure: PRESSURE, EV: EV_VALUE
INFO  | ✨ TREND/REVERSION SIGNAL ... | EV(raw/eff): +X.X%/+Y.Y% | Regime=trend|range|volatile
```

*   **`[COIN-TIMEFRAME]`**: The market being analyzed (e.g., `btc-5m`, `eth-1h`).
*   **`P: PRICE`**: The current mid-price of the YES token.
*   **`Z: Z-SCORE`**: How many standard deviations the price is from its recent mean (a measure of momentum/overextension).
*   **`RSI: RSI`**: The Relative Strength Index.
*   **`RelVol: REL_VOL`**: Relative Volatility – indicates if the market is stable (near 1.0) or chaotic (higher values). Our "Volatility Regime" filter uses this.
*   **`Pressure: PRESSURE`**: Deep Order Book Imbalance (OBI) – reflects net buying (>0) or selling (<0) pressure across the top 5 order book levels.
*   **`EV: EV_VALUE`**: The calculated Expected Value of a trade (e.g., `+0.03` means a 3% edge).

**3. Step-by-Step Filtering Logic (Example):**

Let's take a sample log entry:
`ANALYSIS [btc-5m] | P: 0.320, Z: -0.58, RSI: 48.2, RelVol: 1.11, Pressure: 0.00, EV: +0.03`

The bot applies its filters in a specific order:

1.  **Price Check (0.20 - 0.45):**
    *   `P: 0.320` is within the "Deep Value Sniper" range. **✅ PASS**
2.  **Expected Value (EV) Check (+0.02 minimum):**
    *   `EV: +0.03` is greater than `+0.02`. **✅ PASS**
3.  **Bitcoin Macro Trend Check:**
    *   (Not shown in this log line, but checked internally) If BTC is trending down, `BUY NO` would be considered. If BTC is trending up, `BUY YES` would be considered. Assuming it matches. **✅ PASS (for this example)**
4.  **Volatility Regime Adjusted Z-Score Check:**
    *   For `MAIN` profile, base `z_thresh` is `0.7`.
    *   For `5m` timeframe, `z_thresh` is scaled up by `1.2` (noise penalty): `1.2 * 1.2 = 1.44`.
    *   `RelVol: 1.11` further scales `z_thresh` (`1.44 * max(1.0, 1.11)`).
    *   The required Z-Score (absolute value) is now above `1.44`.
    *   The current `Z: -0.58` (absolute value `0.58`) is **less than `1.44`**. **❌ FAIL**
5.  **Order Book Pressure Check (e.g., > 0.15 for BUY YES):**
    *   `Pressure: 0.00` is **less than `0.15`**. **❌ FAIL**

Since steps 4 and 5 failed, this market `[btc-5m]` will **NOT** generate a `SNIPER SIGNAL`. This detailed logging helps you understand the exact reasons behind the bot's decisions.

---

### 🧠 Trading Terminology (v20)
*   **Price**: The **CLOB Midpoint** `(Bid+Ask)/2`. 
*   **Safety Zone**: The bot only trades tokens between **$0.15 and $0.85**. Outside this range, liquidity is too low for safe trading.
*   **Symmetric Trading**: The bot can profit from both up-trends (BUY YES) and market crashes (BUY NO).
*   **Active / Total**: Displayed on the dashboard to show current exposure vs total trade volume.
*   **Regime**: The detected market condition at entry time:
    *   `trend` = directional movement is strong.
    *   `range` = mean-reverting/choppy market.
    *   `volatile` = unstable/high-noise condition (bot is stricter or may skip).
*   **Regime PnL**: Profit/loss grouped by entry regime, used to see where the edge exists.
    *   Example: `trend +$12.4 (20 trades)`, `range -$4.1 (18 trades)`, `volatile -$1.8 (5 trades)`.

### ⚙️ Risk Profile (`config.json`)
Single profile for production focus (name `MAIN`).

Current live configuration:
*   `trade_allowed_coins = ["btc"]`
*   `trade_allowed_timeframes = ["15m"]`
*   `max_entries_per_cycle = 1`
*   `min_effective_ev = 0.01`
*   `signal_decay_lambda = 0.008`
*   `max_signal_age_sec = 45`
*   `tp_pct = 0.12`
*   `sl_pct = 0.05`

### 🧪 Fast Evaluation Commands
- **Single Backtest**: `make backtest`
- **WS Replay Backtest**: `make replay`
- **Walk-Forward Replay Validation**: `make walkforward`
- **Parameter Sweep**: `make sweep`
- **Sweep + Auto-Apply (safe gate)**: `make sweep-apply`

Direct sweep examples:
```bash
uv run -m backtest.sweep --rows-limit 0 --top 10
uv run -m backtest.sweep --rows-limit 20000 --apply-best --min-closed-for-apply 30
```

Outputs:
- `db/best_params.json`: best run + ranked top results
- Optional `config.json` update when `--apply-best` passes the minimum closed-trade gate

### 🆕 v39 Replay Data Pipeline

This version adds a historical pipeline for faster, more realistic offline evaluation:

*   **WS Recorder (`ws_ticks`):**
    *   Stores replay-ready microstructure snapshots from live stream events:
        *   bid/ask, mid, spread
        *   top-5 depth totals and pressure
        *   event type and timestamps
*   **SQL Paper Trade Mirror (`paper_trades`):**
    *   Every paper entry/exit is now mirrored to SQLite with stable `trade_id` and lifecycle fields.
    *   SQLite is the runtime source of truth for dashboard and paper trading.
*   **Replay Backtester (`backtest.replay`):**
    *   Replays `ws_ticks` in time order.
    *   Reuses current signal logic + profile filters.
    *   Applies fill friction model (spread, depth impact, latency/slippage penalties).
*   **Walk-Forward Validator (`backtest.walkforward`):**
    *   Tunes selected params on train windows and validates on forward windows.
    *   Produces out-of-sample summary to reduce overfitting risk.

### 🆕 v40 SQLite Portfolio Core

Paper trading now uses SQLite as the runtime source of truth (JSON is legacy):

*   **`paper_portfolio_state` (state table):**
    *   Stores current portfolio state (`balance`, `high_water_mark`, `initial_balance`).
    *   Used by risk checks, sizing, and dashboard totals.
*   **`paper_trades` (ledger table):**
    *   Stores each paper trade lifecycle (`OPEN` → `CLOSED`) with full metadata.
    *   Used by dashboard history, coin gate analytics, and post-trade analysis.
*   **Legacy JSON migration:**
    *   If `db/paper_portfolio.json` exists, it is auto-migrated on startup and renamed to `.migrated`.
*   **Coin Gate Deadlock Guard:**
    *   Prevents blocking all configured entry coins at once.

### 🆕 v35 Runtime Stability

This version hardens live execution consistency and signal quality:

*   **YES/NO Mapping Fix:**
    *   Market parsing now maps to the correct YES-side token/outcome rather than assuming index `0`.
*   **One Active Contract per Coin-Timeframe:**
    *   Engine keeps only the latest active contract per key (e.g., `btc-15m`) to avoid mixed-window signal noise.
*   **Broken Book Snapshot Guard:**
    *   Invalid top-of-book snapshots (bad bid/ask or unrealistic spread) are ignored.
*   **Stable Tick Ordering:**
    *   Recent series reads now use insertion order (`id DESC`) to avoid intra-second ordering anomalies.
*   **WS Parser Robustness:**
    *   Handles list payloads safely without callback parse errors.

### 🆕 v36 Execution Safety & Monitoring

This version adds portfolio-protection controls and richer diagnostics:

*   **Automatic Coin Gate:**
    *   Blocks new entries for weak coins using rolling win-rate + expectancy thresholds.
    *   Config keys per risk profile:
        *   `coin_gate_enabled`
        *   `coin_gate_min_closed_trades`
        *   `coin_gate_lookback_trades`
        *   `coin_gate_min_win_rate`
        *   `coin_gate_max_expectancy`
*   **Stale Position Auto-Close:**
    *   If a market stops streaming and trade exceeds max hold horizon, it force-closes with `STALE_TIMEOUT` and releases capital.
*   **Profile-Based TP/SL:**
    *   Paper exits now read `tp_pct` and `sl_pct` from selected risk profile.
*   **Dashboard Per-Coin Panel:**
    *   Displays per-coin `trades`, `win_rate`, `pnl`, `avg_move_pct`, and `median_move_pct`.
*   **Per-Trade PnL Display:**
    *   Trade history shows PnL in both USD and percentage.

### 📊 Metrics Status (Dashboard vs Not Yet)

Already visible in dashboard:
*   `total_pnl`, `roi`, `win_rate`, `expectancy`
*   `active_count`, `closed_count`, `total_trades`
*   `avg_signal_age_sec`
*   `max_drawdown_pct`
*   `zero_hold_exit_ratio`
*   `regime_pnl`
*   `exit_reasons`
*   `per-coin analysis` (trades/win-rate/pnl/avg/median move)
*   `per-trade PnL` ($ and %)

Not yet shown directly on dashboard (available from logs/data):
*   Rolling coin expectancy windows used by coin gate

### 📘 Dashboard Metrics Glossary

*   **Total PnL (`total_pnl`)**: Sum of realized PnL from closed trades.
*   **ROI (`roi`)**: `total_pnl / initial_balance * 100` (initial balance = `$1000`).
*   **Win Rate (`win_rate`)**: Percent of closed trades with positive PnL.
*   **Expectancy (`expectancy`)**: Average realized PnL per closed trade.
*   **Active / Finished / Total**:
    *   `active_count` = currently open paper trades
    *   `finished` = closed trades count
    *   `total_trades` = active + closed
*   **Avg Signal Age (`avg_signal_age_sec`)**: Average signal age at entry for trades that recorded it.
*   **Max Drawdown (`max_drawdown_pct`)**: Largest peak-to-trough equity drop (reconstructed from closed-trade PnL stream).
*   **Zero-Hold Exits (`zero_hold_exit_ratio`)**: Percent of closed trades with `hold_seconds == 0`.
*   **Regime PnL (`regime_pnl`)**: Realized PnL grouped by entry regime (`trend`, `range`, `volatile`, `unknown`).
*   **Exit Reasons (`exit_reasons`)**: Count by exit label (`TP`, `SL`, `TIME`, `EV_FLIP`, `PRESSURE_FLIP`, `STALE_TIMEOUT`, etc.).
*   **Per Coin Analysis (`per_coin`)**:
    *   `trades`: closed trades for that coin
    *   `win_rate`: positive-PnL trade ratio
    *   `pnl`: total realized PnL
    *   `avg_move_pct` / `median_move_pct`: average/median realized move%
*   **Per-Trade PnL (History Table)**:
    *   `$` = realized PnL in dollars
    *   `%` = realized move percentage for that specific trade

### 📌 Current Research Conclusion

Recent sweep and replay work leads to the current operating decision:

*   **Keep live trading on `BTC 15m` only.**
*   **Trend logic is the only component with evidence of edge in current backtests.**
*   **`BTC 5m` is currently disabled for live trading.**
*   **Mean-reversion-only sweeps produced zero trades on the tested samples.**
*   **Late-expiry dominance strategy is not validated and is not a live candidate.**

Backtest summary used for the current live config:

*   `BTC 15m` sweep on `100000` rows was positive.
    *   Best region clustered around `min_ev=0.01`, `decay=0.008-0.012`, `topN=1`, `tp=0.12`, `sl=0.05-0.06`.
    *   Best row: `87 trades`, `52.9% win`, `expectancy +0.0142`, `profit factor 1.23`.
*   `BTC 5m` sweep on `100000` rows was negative across the tested grid.
*   `--disable-trend` sweeps produced `0` trades, so current edge is not coming from mean reversion.

This is why `config.json` is currently set to `BTC 15m` with one-entry, trend-focused parameters.
