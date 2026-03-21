# 🤖 Polymarket Trading Bot: Project Guide

This project is a high-frequency trading bot designed for Polymarket crypto "Up/Down" events. It uses institutional-grade technical analysis, real-time orderbook safety guards, and a secure web dashboard.

📜 **Sequential Summary of Development**

*   **Version 1-8:** Foundation, RSI/Z-Score integration, and Major Trend filtering.
*   **Version 9-10:** CLOB Spread Guard and Open Interest (OI) conviction filtering.
*   **Version 11:** Multi-Profile Risk (Conservative/Balanced/Aggressive) and sizing.
*   **Version 12 (Current):** Secure Live Dashboard & Nginx Deployment.
    *   **Dashboard:** Real-time Tailwind CSS UI to monitor balance, active trades, and history.
    *   **Security:** Session-based password protection and encrypted cookies.
    *   **Deployment:** Nginx reverse proxy integration for EC2 production environments.

---

### 🛠 Tools & Technologies
- **Language:** Python 3.12+ (uv manager)
- **Web Engine:** Flask (Dashboard API & UI)
- **Deployment:** Nginx (Reverse Proxy)
- **Database:** SQLite (History) & JSON (Real-time Portfolio)
- **APIs:** Gamma, CLOB (Orderbook), Data (Open Interest)

### 📂 Directory Structure
- **`app/`**: Entry point, **Web Dashboard**, and Profiles.
- **`core/`**: The async engine loop (The "Heart").
- **`data/`**: Multi-API Clients and Storage.
- **`strategy/`**: Signal logic and **Paper Trading** module.
- **`db/`**: Persistent storage (SQLite, JSON Portfolio, PID files).

### 🚀 Quick Start
1.  **Configure**: Fill in `.env` (API Keys, `DASHBOARD_PASSWORD`, `FLASK_SECRET_KEY`).
2.  **Start Bot**: `make run`
3.  **Start Dashboard**: `make dashboard`
4.  **Access UI**: Visit `http://<your-ec2-ip>` (Ensure Port 80 is open in AWS Security Groups).

### 📈 Monitoring & Maintenance
- **Dashboard**: `make dashboard` (Check port 5000/80)
- **Live Logs**: `make logs`
- **Backtest**: `make backtest`
- **Status**: `make status`

---

### ⚙️ Risk & Sizing Profiles
Adjust these in your `.env` to change how the bot behaves:

| Profile | Strategy Stance | Thresholds |
| :--- | :--- | :--- |
| **Conservative** | Safety First | Z-Score 1.5, High Volume, Tight Spread |
| **Balanced** | Growth | Z-Score 1.2, Med Volume, Med Spread |
| **Aggressive** | High Frequency | Z-Score 0.8, Low Volume, Wide Spread |

*   **SIZING_PROFILE**: Set to `FIXED` ($100) or `PERCENTAGE` (5% of balance).

### 🛡 Security Requirements
To keep your bot private on the public internet:
1.  **AWS Security Group**: Open Port 80 (HTTP) and Port 22 (SSH).
2.  **Dashboard Lock**: Access is restricted via the password set in your `.env`.
3.  **Nginx**: Handles traffic routing from the web to the internal Flask server.
