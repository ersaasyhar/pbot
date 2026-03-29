# Polymarket Trading Bot

Rule-based Polymarket trading and research framework with:
- Live market ingestion (REST + WebSocket)
- Signal engine (trend/reversion, EV filters, gating)
- Paper portfolio execution and analytics
- Replay/backtest/walk-forward evaluation pipeline
- Account utility tools for Polymarket APIs

## 30-Second Start
```bash
cp .env.example .env
# edit .env and config.json
uv sync
make run
make dashboard
```

Then:
- Bot status: `make status`
- Logs: `make logs`
- Replay test: `make replay`

## Table of Contents
- [1. What This Project Is](#1-what-this-project-is)
- [2. System Flow](#2-system-flow)
- [3. Repository Layout](#3-repository-layout)
- [4. Readme Map](#4-readme-map)
- [5. Prerequisites](#5-prerequisites)
- [6. Configuration](#6-configuration)
- [7. Quick Start](#7-quick-start)
- [8. Runtime Modes (systemd vs nohup)](#8-runtime-modes-systemd-vs-nohup)
- [9. Main Commands](#9-main-commands)
- [10. Code Quality (Pre-Commit + CI)](#10-code-quality-pre-commit--ci)
- [11. Backtest and Research Workflow](#11-backtest-and-research-workflow)
- [12. Strategy Profiles](#12-strategy-profiles)
- [13. Polymarket Account Tools](#13-polymarket-account-tools)
- [14. Data and Storage](#14-data-and-storage)
- [15. Risk Model Summary](#15-risk-model-summary)
- [16. Troubleshooting](#16-troubleshooting)
- [17. Security Notes](#17-security-notes)

## 1. What This Project Is
This project is a Python-based trading/research system centered on Polymarket crypto event markets.

Current production focus:
- Coin: `btc`
- Timeframe: `15m`
- Profile: `MAIN`

Primary goal:
- Run selective, risk-contained paper execution with measurable performance and replay-based evaluation.

## 2. System Flow
1. Fetch active markets and stream book/price updates.
2. Build features (z-score, RSI, momentum, rel-vol, pressure proxy).
3. Generate signal and confidence.
4. Apply EV, spread, liquidity, age-decay, and gating filters.
5. Queue and execute top candidates under exposure/risk constraints.
6. Manage exits with TP/SL/time/stale logic.
7. Persist runtime state/trades to SQLite.
8. Evaluate strategy using backtest/replay/walk-forward.

## 3. Repository Layout
- `app/`: Runtime bootstrap, config, dashboard
- `core/`: Live engine orchestration
- `core/services/`: Runtime service modules
- `data/`: Clients + storage facade
- `data/repositories/`: SQLite repository layer
- `strategy/`: Signal + paper trading
- `strategy/paper/`: Paper trading submodules
- `features/`: Feature engineering
- `backtest/`: Backtest/replay/walk-forward/sweep
- `tools/`: Operational CLI utilities
- `scripts/`: Ad-hoc dev/debug scripts
- `db/`: Local DB artifacts
- `tests/`: Unit tests

## 4. Readme Map
Each major folder has its own `README.md`:
- [app/README.md](app/README.md)
- [core/README.md](core/README.md)
- [core/services/README.md](core/services/README.md)
- [data/README.md](data/README.md)
- [data/repositories/README.md](data/repositories/README.md)
- [strategy/README.md](strategy/README.md)
- [strategy/paper/README.md](strategy/paper/README.md)
- [backtest/README.md](backtest/README.md)
- [features/README.md](features/README.md)
- [tools/README.md](tools/README.md)
- [scripts/README.md](scripts/README.md)
- [db/README.md](db/README.md)
- [tests/README.md](tests/README.md)

Recommended reading order:
1. Root `README.md`
2. `app/README.md` + `core/README.md`
3. Domain folder README where you are editing code

## 5. Prerequisites
- Python `3.12+`
- `uv` package manager
- Valid `.env` for any authenticated Polymarket/API operations

Optional for server deployments:
- `systemd`
- `nginx`

## 6. Configuration
Main config files:
- `.env` (secrets and runtime env)
- `config.json` (risk/sizing profiles and runtime filters)

Current selected config keys:
- `risk_profiles.SELECTED = MAIN`
- `sizing_profiles.SELECTED = FIXED`

Important `MAIN` controls:
- `trade_allowed_coins`
- `trade_allowed_timeframes`
- `min_effective_ev`
- `signal_decay_lambda`
- `max_signal_age_sec`
- `max_entries_per_cycle`
- `tp_pct`, `sl_pct`
- `max_spread`, `min_depth_top5`
- `mode` (`main` or `hold`)
- `no_trade_yes_min`, `no_trade_yes_max`
- `min_strike_displacement`
- `require_multi_tf_confirmation`, `confirmation_timeframes`
- `contextual_sl_enabled`, `non_dominant_sl_pct`, `early_sl_pct`
- `max_entry_slippage_abs`

Discovery controls (optional, under `bot`):
- `discovery_allowed_timeframes` lets you ingest additional market windows for research
  without changing entry/trade timeframes in the selected risk profile.
- `external_context_enabled`, `external_spot_symbol`, `external_perp_symbol`,
  `perp_poll_interval_sec` control BTC spot/perp context collectors.

Config is validated at startup (`app/config_validation.py`).

## 7. Quick Start
1. Install deps (if needed):
```bash
uv sync
```

2. Prepare env:
```bash
cp .env.example .env
# then edit .env and config.json
```

3. Run bot:
```bash
make run
```

4. Run dashboard:
```bash
make dashboard
```

5. Check status/logs:
```bash
make status
make logs
```

## 8. Runtime Modes (systemd vs nohup)
The `Makefile` is mode-aware:
- If `pbot-bot.service` / `pbot-dashboard.service` exist, it uses `systemd`.
- Otherwise it falls back to local `nohup` + PID files.

## 9. Main Commands
Core operations:
- `make setup`
- `make run`
- `make stop`
- `make dashboard`
- `make dashboard-stop`
- `make status`
- `make logs`
- `make reset-portfolio`
- `make context-stats`

Research/evaluation:
- `make backtest`
- `make replay`
- `make replay-ab`
- `make walkforward`
- `make sweep`
- `make sweep-apply`

## 10. Code Quality (Pre-Commit + CI)
Local guard (recommended on every machine/clone):
```bash
make setup
```

`make setup` does:
- `uv sync`
- `uvx pre-commit install --install-hooks`

Pre-commit hooks configured in `.pre-commit-config.yaml`:
- `ruff-check --fix`
- `ruff-format`

Remote guard (for missed local setup):
- GitHub Actions workflow: `.github/workflows/ci.yml`
- Runs on push/PR:
  - `ruff check`
  - `ruff format --check`
  - unit tests (`tests.test_strategy_utils`)

## 11. Backtest and Research Workflow
Typical flow:
1. Baseline check
```bash
make backtest
```

2. Replay with recorded microstructure
```bash
make replay
```

3. Walk-forward validation
```bash
make walkforward
```

4. Parameter search
```bash
make sweep
```

A/B profile comparison pattern (example):
```bash
uv run -m backtest.replay --profile MAIN --rows-limit 0
uv run -m backtest.replay --profile MAIN_HOLD --rows-limit 0
make replay-ab
```

Replay now prints diagnostics automatically:
- `resolved_alignment_rate` (overall + by timeframe/side/setup)
- `sl_saved_loss_vs_cut_winner`
- `setup_expectancy_pct_per_trade`

Run `MAIN_HOLD` on `5m` only (after `ws_ticks` has `5m` rows):
```bash
UV_CACHE_DIR=.uv-cache uv run python - <<'PY'
from app.config import RISK_PROFILES
from backtest.replay import load_ws_rows, run_replay, resolve_stake_usd
p = dict(RISK_PROFILES["MAIN_HOLD"])
p["trade_allowed_timeframes"] = ["5m"]
rows = load_ws_rows(p, rows_limit=0)
print("rows", len(rows))
r = run_replay(rows, p, stake_usd=resolve_stake_usd(10.0), latency_ms=250, extra_slippage=0.001)
print(r)
PY
```

## 12. Strategy Profiles
- `MAIN`: current baseline strategy profile.
- `MAIN_HOLD`: hold-to-resolution variant for your manual style hypothesis.

`MAIN_HOLD` key differences:
- `tp_pct = 5.0` (effectively disables normal TP exits)
- `sl_pct = 0.30` (catastrophic/emergency stop)
- Entry filters and market constraints remain aligned with `MAIN` for fair A/B tests.

Recommended A/B command:
```bash
make replay-ab
```

## 13. Polymarket Account Tools
Primary utility:
```bash
uv run -m tools.polymarket_account --help
```

Make wrappers:
- `make account-whoami`
- `make account-balance`
- `make account-trades`
- `make account-orders`
- `make account-public-trades`
- `make account-activity`

Order placement commands support dry-run patterns first and explicit confirmation for posting/canceling.

## 14. Data and Storage
SQLite tables used by runtime/research:
- `market_prices`
- `ws_ticks`
- `external_spot_ticks`
- `perp_context_ticks`
- `paper_trades`
- `paper_portfolio_state`

Storage API entrypoint:
- `data/storage.py` (facade)

Concrete SQL modules:
- `data/repositories/*`

## 15. Risk Model Summary
Core protections currently in place:
- EV-based trade rejection
- Spread and liquidity filters
- Signal age decay and top-N candidate selection
- Coin gate using rolling closed-trade stats
- Exposure limits (coin and side)
- Drawdown-sensitive stake sizing
- Circuit breaker logic
- TP/SL + time/stale exit handling

## 16. Troubleshooting
`uv` cache/write issues on restricted environments:
```bash
mkdir -p .uv-cache
UV_CACHE_DIR=.uv-cache make replay
```

No replay data available:
- `make replay` returns no rows when `ws_ticks` is empty.
- Run collector/bot first to build local WS history.

Config startup failures:
- Check selected profile names and required keys in `config.json`.

## 17. Security Notes
- Never commit real secrets from `.env`.
- Treat account exports and private CSVs as sensitive.
- Keep DB and logs out of commits unless explicitly needed.
