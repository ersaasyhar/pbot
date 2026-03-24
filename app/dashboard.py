from flask import Flask, render_template, jsonify, request, redirect, session, url_for
import os
import statistics
from dotenv import load_dotenv
from app.config import SELECTED_RISK_PROFILE_NAME
from data.storage import load_paper_portfolio_snapshot

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-fallback-key")

DASHBOARD_PASS = os.getenv("DASHBOARD_PASSWORD", "admin")


def get_data():
    data = load_paper_portfolio_snapshot(history_limit=5000)

    # Calculate Metrics
    history = data.get("history", [])
    normalized_history = []
    for t in history:
        trade = dict(t)
        trade_pnl = float(trade.get("pnl", 0.0))
        if trade.get("move_pct") is not None:
            trade_pnl_pct = float(trade.get("move_pct"))
        else:
            entry_cost = float(trade.get("entry_cost", 0.0) or 0.0)
            trade_pnl_pct = (trade_pnl / entry_cost * 100.0) if entry_cost > 0 else 0.0
        trade["trade_pnl"] = round(trade_pnl, 2)
        trade["trade_pnl_pct"] = round(trade_pnl_pct, 2)
        normalized_history.append(trade)
    history = normalized_history
    data["history"] = history
    active = data.get("active_trades", {})

    wins = [t for t in history if t.get("pnl", 0) > 0]
    losses = [t for t in history if t.get("pnl", 0) <= 0]

    total_pnl = sum(t.get("pnl", 0) for t in history)
    initial_balance = float(data.get("initial_balance", 1000.0) or 1000.0)
    roi = (total_pnl / initial_balance) * 100

    win_rate = (len(wins) / len(history) * 100) if history else 0
    expectancy = (total_pnl / len(history)) if history else 0.0
    zero_hold_count = sum(1 for t in history if int(t.get("hold_seconds", 0)) == 0)
    zero_hold_exit_ratio = (
        (zero_hold_count / len(history) * 100.0) if history else 0.0
    )

    # Reconstruct equity from closed-trade pnl stream to estimate drawdown.
    equity = initial_balance
    peak = initial_balance
    max_drawdown_pct = 0.0
    for t in history:
        equity += float(t.get("pnl", 0.0))
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

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

    # Per-coin performance
    coin_perf = {}
    for t in history:
        coin = (t.get("coin") or "unknown").lower()
        if coin not in coin_perf:
            coin_perf[coin] = {"trades": 0, "wins": 0, "pnl": 0.0, "moves": []}
        coin_perf[coin]["trades"] += 1
        pnl = float(t.get("pnl", 0.0))
        if pnl > 0:
            coin_perf[coin]["wins"] += 1
        coin_perf[coin]["pnl"] += pnl
        coin_perf[coin]["moves"].append(float(t.get("move_pct", 0.0)))

    per_coin_stats = []
    for coin, s in coin_perf.items():
        trades = s["trades"]
        win_rate_coin = (s["wins"] / trades * 100.0) if trades else 0.0
        avg_move = statistics.mean(s["moves"]) if s["moves"] else 0.0
        median_move = statistics.median(s["moves"]) if s["moves"] else 0.0
        per_coin_stats.append(
            {
                "coin": coin,
                "trades": trades,
                "win_rate": round(win_rate_coin, 1),
                "pnl": round(s["pnl"], 2),
                "avg_move_pct": round(avg_move, 2),
                "median_move_pct": round(median_move, 2),
            }
        )
    per_coin_stats.sort(key=lambda x: x["pnl"], reverse=True)

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
        "max_drawdown_pct": round(max_drawdown_pct * 100.0, 2),
        "zero_hold_exit_ratio": round(zero_hold_exit_ratio, 2),
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
        "per_coin": per_coin_stats,
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
