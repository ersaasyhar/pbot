# --- Polymarket Bot Makefile ---

PYTHONPATH_EXPORT = export PYTHONPATH=.
PID_FILE = db/bot.pid
DASHBOARD_PID = db/dashboard.pid
PORTFOLIO_FILE = db/paper_portfolio.json

.PHONY: help run backtest sweep sweep-apply stop status logs clean dashboard dashboard-stop reset-portfolio

help:
	@echo "Available commands:"
	@echo "  make run             - Start the bot in the background"
	@echo "  make backtest        - Run the historical backtester"
	@echo "  make sweep           - Run parameter sweep for fast calibration"
	@echo "  make sweep-apply     - Run sweep and apply best params to selected profile"
	@echo "  make stop            - Stop the background bot"
	@echo "  make dashboard       - Start the web dashboard"
	@echo "  make dashboard-stop  - Stop the web dashboard"
	@echo "  make status          - Check if bot & dashboard are running"
	@echo "  make logs            - View the latest bot logs"
	@echo "  make clean           - Remove logs and temp files"
	@echo '  make reset-portfolio - Reset virtual balance to $$1000 and clear trades'

run: stop
	@echo "🚀 Starting Polymarket Bot..."
	@mkdir -p db
	@$(PYTHONPATH_EXPORT) && nohup uv run -m app.main > collector.log 2>&1 & echo $$! > $(PID_FILE)
	@echo "✅ Bot started. Use 'make logs' to monitor."

dashboard: dashboard-stop
	@echo "🖥️ Starting Dashboard on port 5000..."
	@$(PYTHONPATH_EXPORT) && nohup uv run app/dashboard.py > dashboard.log 2>&1 & echo $$! > $(DASHBOARD_PID)
	@echo "✅ Dashboard started. Access at http://your-ec2-ip:5000"

dashboard-stop:
	@if [ -f $(DASHBOARD_PID) ]; then \
		PID=$$(cat $(DASHBOARD_PID)); \
		echo "🛑 Stopping Dashboard (PID $$PID)..."; \
		kill $$PID 2>/dev/null || true; \
		rm -f $(DASHBOARD_PID); \
	fi

backtest:
	@echo "📈 Running Backtest..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.runner

sweep:
	@echo "🧪 Running Parameter Sweep..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.sweep

sweep-apply:
	@echo "🧪 Running Sweep + Applying Best Params..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.sweep --rows-limit 0 --apply-best --min-closed-for-apply 30

stop:
	@echo "🛑 Stopping Polymarket Bot..."
	@if [ -f $(PID_FILE) ]; then \
		kill $$(cat $(PID_FILE)) 2>/dev/null || true; \
		rm -f $(PID_FILE); \
	fi
	@# Force kill any orphaned processes to prevent duplicates
	@# Use a specific pattern to avoid killing the make process itself
	@pkill -f "[u]v run -m app.main" 2>/dev/null || true
	@echo "✅ Bot stopped."

reset-portfolio: stop dashboard-stop
	@echo "🗑️ Resetting Paper Portfolio..."
	@rm -f $(PORTFOLIO_FILE)
	@echo "✅ Portfolio deleted. Starting fresh bot..."
	@$(MAKE) --no-print-directory run
	@$(MAKE) --no-print-directory dashboard

status:
	@if [ -f $(PID_FILE) ] && ps -p $$(cat $(PID_FILE)) > /dev/null; then echo "🟢 Bot: RUNNING"; else echo "🔴 Bot: STOPPED"; fi
	@if [ -f $(DASHBOARD_PID) ] && ps -p $$(cat $(DASHBOARD_PID)) > /dev/null; then echo "🟢 Dashboard: RUNNING (Port 5000)"; else echo "🔴 Dashboard: STOPPED"; fi

logs:
	@tail -f collector.log

clean:
	@echo "🧹 Cleaning up..."
	rm -f current.log collector.log dashboard.log $(PID_FILE) $(DASHBOARD_PID)
	find . -type d -name "__pycache__" -exec rm -rf {} +
