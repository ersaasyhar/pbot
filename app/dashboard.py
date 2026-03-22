from flask import Flask, render_template, jsonify, request, redirect, session, url_for
import json
import os
from dotenv import load_dotenv
from app.config import SELECTED_RISK_PROFILE_NAME

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-fallback-key")

PORTFOLIO_PATH = "db/paper_portfolio.json"
DASHBOARD_PASS = os.getenv("DASHBOARD_PASSWORD", "admin")


def get_data():
    if not os.path.exists(PORTFOLIO_PATH):
        data = {
            "balance": 1000.0,
            "high_water_mark": 1000.0,
            "active_trades": {},
            "history": [],
        }
    else:
        with open(PORTFOLIO_PATH, "r") as f:
            data = json.load(f)

    # Calculate Metrics
    history = data.get("history", [])
    active = data.get("active_trades", {})

    wins = [t for t in history if t.get("pnl", 0) > 0]
    losses = [t for t in history if t.get("pnl", 0) <= 0]

    total_pnl = sum(t.get("pnl", 0) for t in history)
    initial_balance = 1000.0
    roi = (total_pnl / initial_balance) * 100

    win_rate = (len(wins) / len(history) * 100) if history else 0
    expectancy = (total_pnl / len(history)) if history else 0.0

    # Entry quality proxy: younger signal age at entry is generally better.
    entry_ages = [
        t.get("signal_age_sec") for t in history if t.get("signal_age_sec") is not None
    ]
    avg_signal_age_sec = (sum(entry_ages) / len(entry_ages)) if entry_ages else None

    # Regime performance view
    regime_perf = {
        "trend": {"pnl": 0.0, "trades": 0},
        "range": {"pnl": 0.0, "trades": 0},
        "volatile": {"pnl": 0.0, "trades": 0},
        "unknown": {"pnl": 0.0, "trades": 0},
    }
    for t in history:
        regime = t.get("regime_at_entry") or "unknown"
        if regime not in regime_perf:
            regime_perf[regime] = {"pnl": 0.0, "trades": 0}
        regime_perf[regime]["pnl"] += float(t.get("pnl", 0.0))
        regime_perf[regime]["trades"] += 1

    # Exit efficiency proxy
    exit_reasons = {}
    for t in history:
        reason = t.get("exit_reason", "UNKNOWN")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    metrics = {
        "total_pnl": round(total_pnl, 2),
        "roi": round(roi, 2),
        "win_rate": round(win_rate, 1),
        "expectancy": round(expectancy, 4),
        "total_trades": len(history) + len(active),
        "closed_count": len(history),
        "active_count": len(active),
        "wins": len(wins),
        "losses": len(losses),
        "risk_profile": SELECTED_RISK_PROFILE_NAME,
        "avg_signal_age_sec": round(avg_signal_age_sec, 2)
        if avg_signal_age_sec is not None
        else None,
        "regime_pnl": {
            k: {"pnl": round(v["pnl"], 2), "trades": v["trades"]}
            for k, v in regime_perf.items()
        },
        "exit_reasons": exit_reasons,
    }

    data["metrics"] = metrics
    return data


@app.before_request
def require_login():
    allowed_routes = ["login", "static"]
    if "logged_in" not in session and request.endpoint not in allowed_routes:
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASS:
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            error = "Invalid password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


@app.route("/")
def index():
    data = get_data()
    return render_template("index.html", data=data)


@app.route("/api/data")
def api_data():
    if "logged_in" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(get_data())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
