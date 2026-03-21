from flask import Flask, render_template, jsonify, request, redirect, session, url_for
import json
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-fallback-key")

PORTFOLIO_PATH = "db/paper_portfolio.json"
DASHBOARD_PASS = os.getenv("DASHBOARD_PASSWORD", "admin")

def get_data():
    if not os.path.exists(PORTFOLIO_PATH):
        return {"balance": 1000.0, "active_trades": {}, "history": []}
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)

# --- AUTH PROTECTOR ---
@app.before_request
def require_login():
    # List of endpoints that DON'T require a password
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
            error = "Invalid password. Access denied."
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
