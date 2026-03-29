# --- Polymarket Bot Makefile ---

PYTHONPATH_EXPORT = export PYTHONPATH=.
PID_FILE = db/bot.pid
DASHBOARD_PID = db/dashboard.pid
PORTFOLIO_FILE = db/paper_portfolio.json
BOT_SERVICE = pbot-bot
DASHBOARD_SERVICE = pbot-dashboard

.PHONY: help setup run backtest replay replay-ab walkforward walkforward-ab sweep sweep-apply stop status logs clean dashboard dashboard-stop reset-portfolio context-stats account-whoami account-balance account-trades account-orders account-public-trades account-activity

help:
	@echo "Available commands:"
	@echo "  make setup           - Install deps and git pre-commit hooks"
	@echo "  make run             - Start the bot in the background"
	@echo "  make backtest        - Run the historical backtester"
	@echo "  make replay          - Run WS tick replay backtest with friction model"
	@echo "  make replay-ab       - Compare MAIN vs MAIN_HOLD on same replay window"
	@echo "  make walkforward     - Run walk-forward tuning/validation on WS replay data"
	@echo "  make walkforward-ab  - Walk-forward A/B with min-trade filter per fold"
	@echo "  make sweep           - Run parameter sweep for fast calibration"
	@echo "  make sweep-apply     - Run sweep and apply best params to selected profile"
	@echo "  make stop            - Stop the background bot"
	@echo "  make dashboard       - Start the web dashboard"
	@echo "  make dashboard-stop  - Stop the web dashboard"
	@echo "  make status          - Check if bot & dashboard are running"
	@echo "  make logs            - View the latest bot logs"
	@echo "  make clean           - Remove logs and temp files"
	@echo '  make reset-portfolio - Reset virtual balance to $$1000 and clear trades'
	@echo "  make context-stats   - Show latest external context row counts"
	@echo "  make account-whoami  - Show wallet address from .env credentials"
	@echo "  make account-balance - Show collateral balance + allowance"
	@echo "  make account-trades  - Show recent account trades"
	@echo "  make account-orders  - Show open orders"
	@echo "  make account-public-trades - Show trades from Data API by user address"
	@echo "  make account-activity - Show activity feed from Data API by user address"

setup:
	@echo "🔧 Installing dependencies and pre-commit hooks..."
	@uv sync
	@uvx pre-commit install --install-hooks
	@echo "✅ Setup complete. Pre-commit hooks are active."

run: stop
	@echo "🚀 Starting Polymarket Bot..."
	@if systemctl list-unit-files | grep -q "^$(BOT_SERVICE).service"; then \
		sudo systemctl restart $(BOT_SERVICE); \
	else \
		mkdir -p db; \
		$(PYTHONPATH_EXPORT) && nohup uv run -m app.main > collector.log 2>&1 & echo $$! > $(PID_FILE); \
	fi
	@echo "✅ Bot started. Use 'make logs' to monitor."

dashboard: dashboard-stop
	@echo "🖥️ Starting Dashboard on port 5000..."
	@if systemctl list-unit-files | grep -q "^$(DASHBOARD_SERVICE).service"; then \
		sudo systemctl restart $(DASHBOARD_SERVICE); \
	else \
		$(PYTHONPATH_EXPORT) && nohup uv run app/dashboard.py > dashboard.log 2>&1 & echo $$! > $(DASHBOARD_PID); \
	fi
	@echo "✅ Dashboard started. Access at http://<your-ec2-ip>:5000 or http://localhost:5000"

dashboard-stop:
	@if systemctl list-unit-files | grep -q "^$(DASHBOARD_SERVICE).service"; then \
		echo "🛑 Stopping Dashboard service ($(DASHBOARD_SERVICE))..."; \
		sudo systemctl stop $(DASHBOARD_SERVICE); \
	elif [ -f $(DASHBOARD_PID) ]; then \
		PID=$$(cat $(DASHBOARD_PID)); \
		echo "🛑 Stopping Dashboard (PID $$PID)..."; \
		kill $$PID 2>/dev/null || true; \
		rm -f $(DASHBOARD_PID); \
	fi

backtest:
	@echo "📈 Running Backtest..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.runner

replay:
	@echo "🎬 Running WS Replay Backtest..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.replay

replay-ab:
	@echo "🆚 Running A/B Replay (MAIN vs MAIN_HOLD)..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.ab_compare --profile-a MAIN --profile-b MAIN_HOLD --rows-limit 0

walkforward:
	@echo "🧪 Running Walk-Forward Replay Validation..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.walkforward

walkforward-ab:
	@echo "🧪 Running Walk-Forward A/B (MAIN vs MAIN_HOLD)..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.walkforward_ab --profile-a MAIN --profile-b MAIN_HOLD --rows-limit 0 --folds 6 --min-closed-test 3

sweep:
	@echo "🧪 Running Parameter Sweep..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.sweep

sweep-apply:
	@echo "🧪 Running Sweep + Applying Best Params..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.sweep --rows-limit 0 --apply-best --min-closed-for-apply 30

stop:
	@echo "🛑 Stopping Polymarket Bot..."
	@if systemctl list-unit-files | grep -q "^$(BOT_SERVICE).service"; then \
		sudo systemctl stop $(BOT_SERVICE); \
	elif [ -f $(PID_FILE) ]; then \
		kill $$(cat $(PID_FILE)) 2>/dev/null || true; \
		rm -f $(PID_FILE); \
	fi
	@# Force kill any orphaned processes to prevent duplicates
	@# Use a specific pattern to avoid killing the make process itself
	@pkill -f "[u]v run -m app.main" 2>/dev/null || true
	@echo "✅ Bot stopped."

reset-portfolio: stop dashboard-stop
	@echo "🗑️ Resetting Paper Portfolio..."
	@$(PYTHONPATH_EXPORT) && uv run python -c "from data.storage import init_db, reset_paper_trading_state; init_db(); reset_paper_trading_state(1000.0)"
	@echo "✅ Portfolio deleted. Starting fresh bot..."
	@$(MAKE) --no-print-directory run
	@$(MAKE) --no-print-directory dashboard

context-stats:
	@$(PYTHONPATH_EXPORT) && uv run python -c "import sqlite3; from data.storage import DB_PATH, init_db; init_db(); conn=sqlite3.connect(DB_PATH); c=conn.cursor(); c.execute('SELECT COUNT(*) FROM external_spot_ticks'); s=c.fetchone()[0]; c.execute('SELECT COUNT(*) FROM perp_context_ticks'); p=c.fetchone()[0]; print({'external_spot_ticks': s, 'perp_context_ticks': p}); conn.close()"

status:
	@if systemctl list-unit-files | grep -q "^$(BOT_SERVICE).service"; then \
		if sudo systemctl is-active --quiet $(BOT_SERVICE); then echo "🟢 Bot: RUNNING (systemd)"; else echo "🔴 Bot: STOPPED (systemd)"; fi; \
	else \
		if [ -f $(PID_FILE) ] && ps -p $$(cat $(PID_FILE)) > /dev/null; then echo "🟢 Bot: RUNNING"; else echo "🔴 Bot: STOPPED"; fi; \
	fi
	@if systemctl list-unit-files | grep -q "^$(DASHBOARD_SERVICE).service"; then \
		if sudo systemctl is-active --quiet $(DASHBOARD_SERVICE); then echo "🟢 Dashboard: RUNNING (systemd, Port 5000)"; else echo "🔴 Dashboard: STOPPED (systemd)"; fi; \
	else \
		if [ -f $(DASHBOARD_PID) ] && ps -p $$(cat $(DASHBOARD_PID)) > /dev/null; then echo "🟢 Dashboard: RUNNING (Port 5000)"; else echo "🔴 Dashboard: STOPPED"; fi; \
	fi

logs:
	@if systemctl list-unit-files | grep -q "^$(BOT_SERVICE).service"; then \
		sudo journalctl -u $(BOT_SERVICE) -f; \
	else \
		tail -f collector.log; \
	fi

clean:
	@echo "🧹 Cleaning up..."
	rm -f current.log collector.log dashboard.log $(PID_FILE) $(DASHBOARD_PID)
	find . -type d -name "__pycache__" -exec rm -rf {} +

account-whoami:
	@$(PYTHONPATH_EXPORT) && uv run -m tools.polymarket_account whoami

account-balance:
	@$(PYTHONPATH_EXPORT) && uv run -m tools.polymarket_account balance

account-trades:
	@$(PYTHONPATH_EXPORT) && uv run -m tools.polymarket_account trades

account-orders:
	@$(PYTHONPATH_EXPORT) && uv run -m tools.polymarket_account orders

account-public-trades:
	@$(PYTHONPATH_EXPORT) && uv run -m tools.polymarket_account public-trades

account-activity:
	@$(PYTHONPATH_EXPORT) && uv run -m tools.polymarket_account activity
