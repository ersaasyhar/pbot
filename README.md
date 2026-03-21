# 🤖 Polymarket Trading Bot: Project Guide

This project is a high-frequency trading bot designed for Polymarket crypto "Up/Down" events. 
It uses institutional-grade technical analysis, real-time orderbook safety guards, and conviction filtering via Open Interest.

📜 **Sequential Summary of Development**

*   **Version 1-4:** Foundation, SMA/Z-Score logic, and high-frequency shift (5s interval).
*   **Version 5:** Master Tracker (Tracking all 5m, 15m, 1h, 4h data for major coins).
*   **Version 6:** The Sensitive Strategist (Integrated RSI & EMA confirmation).
*   **Version 7:** The Trend Guard (Added Major SMA trend filter).
*   **Version 8:** Volume Weighted Scorer (Prioritizing high-liquidity markets).
*   **Version 9:** The CLOB Guard & Paper Trader.
*   **Version 10 (Current):** The OI Conviction Filter.
    *   **Open Interest Guard:** Only enters momentum trades if price increase is backed by stable or rising Open Interest (fetching from `data-api`).
    *   **Data Consistency:** Synchronized database schema to track `condition_id` and `open_interest` history.

---

### 🛠 Tools & Technologies
- **Language:** Python 3.12+
- **Package Manager:** `uv`
- **Database:** SQLite (Price/OI history) & JSON (Virtual Portfolio)
- **APIs:** Gamma (Discovery), CLOB (Orderbook), Data (Open Interest)
- **Math:** `numpy` (Z-Score, RSI, SMA, OI-Trend)

### 📂 Directory Structure
- **`app/`**: Main entry point and configuration.
- **`core/`**: The async engine loop and trading logic.
- **`data/`**: Multi-API Clients (Gamma, CLOB, Data) and Storage.
- **`strategy/`**: Signal generation, scoring, and **Paper Trading**.
- **`features/`**: Indicator building (RSI, Z-Score, OI-Trend).
- **`backtest/`**: Historical simulation tools.
- **`tools/`**: Diagnostic utilities.
- **`scripts/`**: Helper scripts.

### 🚀 Quick Start
1.  **Configure**: Fill in your `.env` based on `.env.example`.
2.  **Run Bot**: `make run`
3.  **Check Status**: `make status`

### 📈 Monitoring & Maintenance
- **Live Logs**: `make logs`
- **Portfolio**: `cat db/paper_portfolio.json`
- **Backtest**: `make backtest`

### 🧠 Trading Strategy (v10)
- **Momentum:** Z-Score > 1.5 + Positive Momentum + RSI (55-85).
- **Trend Guard:** Directional alignment with 20-period Major SMA.
- **Conviction:** Momentum breakout requires `OI Trend >= -1%` (confirming new money).
- **Safety:** CLOB Guard blocks trades if Bid/Ask spread > $0.03.

---

### 💡 Developer Feedback: Fetch Intervals & Profitability
- **Current (5s):** Very safe for rate limits (Polymarket allows 100 req/10s). It is highly profitable for **1h/4h** trends and sufficient for **5m** markets due to lower liquidity overhead.
- **Speed vs Sensitivity:** To increase profitability without hitting rate limits, we use the **CLOB Midpoint** instead of "Last Price." This reacts to orderbook changes *before* trades even happen.
- **Recommendation:** Keep 5s for now while gathering Paper Trading data. If we find we are "missing" entries, we can reduce to 2s using authenticated CLOB endpoints.
