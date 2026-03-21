# --- Polymarket Bot Makefile ---

PYTHONPATH_EXPORT = export PYTHONPATH=.

.PHONY: help run backtest stop status logs clean

help:
	@echo "Available commands:"
	@echo "  make run       - Stop existing bot and start a new one in the background"
	@echo "  make backtest  - Run the historical backtester"
	@echo "  make stop      - Stop the background bot process"
	@echo "  make status    - Check if the bot is running"
	@echo "  make logs      - View the latest bot logs"
	@echo "  make clean     - Remove logs and temp files"

run: stop
	@echo "🚀 Starting Polymarket Bot in background..."
	@$(PYTHONPATH_EXPORT) && nohup uv run -m app.main > current.log 2>&1 &
	@echo "✅ Bot started. Use 'make logs' to monitor."

backtest:
	@echo "📈 Running Backtest..."
	@$(PYTHONPATH_EXPORT) && uv run -m backtest.runner

stop:
	@echo "🛑 Stopping Polymarket Bot processes..."
	@pkill -f "uv run -m app.main" || true
	@pkill -f "python3 -m app.main" || true
	@sleep 1

status:
	@ps aux | grep "[a]pp.main" > /dev/null && echo "🟢 Bot is RUNNING" || echo "🔴 Bot is STOPPED"

logs:
	@tail -f current.log

clean:
	@echo "🧹 Cleaning up..."
	rm -f current.log collector.log
	find . -type d -name "__pycache__" -exec rm -rf {} +
