# 🤖 Polymarket Trading Bot: Project Guide

This project is a professional high-frequency trading bot designed for Polymarket crypto "Up/Down" events. It features a real-time WebSocket streamer, a symmetric signal engine, and a secure analytics terminal.

📜 **Development Evolution**
*   **Version 1-16:** REST-based polling, RSI/Z-Score, and CLOB Spread Guard.
*   **Version 18:** WebSocket Streamer (~800 updates per second).
*   **Version 19:** The Safety Zone (Ignoring tokens < $0.15 to avoid high-slippage traps).
*   **Version 20 (Current):** The Precision Guard.
    *   **Symmetric Strategy:** Full support for both **BUY YES** and **BUY NO** signals.
    *   **Percentage-Based Exits:** Switched to **15% Take Profit / 10% Stop Loss** for consistent risk management.
    *   **Mathematical Protection:** Hard caps on PnL to prevent losses from exceeding the initial entry cost.

---

### 🛠 Tools & Technologies
- **Language:** Python 3.12+ (uv manager)
- **Web Engine:** Flask (Secure Terminal UI + Tailwind CSS)
- **Networking:** `websockets` (Real-time CLOB market stream)
- **Database:** SQLite (Price history) & JSON (Virtual Portfolio)
- **APIs:** Gamma (Discovery), CLOB (Execution), Data (Conviction)

### 📂 Directory Structure
- **`config.json`**: **Master Control.** Switch Risk Profiles and Bet Sizes here.
- **`app/`**: Dashboard API, UI Templates, and Config Loader.
- **`core/`**: The high-speed async engine (WebSocket handler).
- **`strategy/`**: Symmetric Signal logic and Paper Trading module.
- **`features/`**: Real-time indicator building (RSI, Z-Score, Trend).
- **`db/`**: Price history, trade history, and PID management.

### 🚀 Quick Start
1.  **Configure**: Fill in `.env` (API Keys) and `config.json` (Risk Profile).
2.  **Run Bot**: `make run`
3.  **Start Dashboard**: `make dashboard`
4.  **Terminal**: Visit `http://<your-ec2-ip>/localhost:5000` (Uses `DASHBOARD_PASSWORD` from `.env`).

### 📈 Maintenance & Commands
- **Check Status**: `make status`
- **Reset Portfolio**: `make reset-portfolio` (Wipes history and returns balance to $1,000)
- **Backtest**: `make backtest` (Matched to your current `config.json` profile)
- **Watch Logs**: `make logs`

---

### 🧠 Trading Terminology (v20)
*   **Price**: The **CLOB Midpoint** `(Bid+Ask)/2`. 
*   **Safety Zone**: The bot only trades tokens between **$0.15 and $0.85**. Outside this range, liquidity is too low for safe trading.
*   **Symmetric Trading**: The bot can profit from both up-trends (BUY YES) and market crashes (BUY NO).
*   **Active / Total**: Displayed on the dashboard to show current exposure vs total trade volume.

### ⚙️ Risk Profiles (`config.json`)
| Profile | Stance | Z-Score | RSI Range | Min Volume |
| :--- | :--- | :--- | :--- | :--- |
| **Conservative** | Safety | 1.5 | 55 - 85 | $2,000 |
| **Balanced** | Growth | 1.2 | 45 - 85 | $500 |
| **Aggressive** | Fast | 0.8 | 35 - 90 | $100 |
