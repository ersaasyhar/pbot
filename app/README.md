# app/

## Purpose
Application layer for runtime bootstrap, config loading/validation, logging, and dashboard UI.

## Key Files
- `main.py`: Bot entrypoint (`uv run -m app.main`).
- `bootstrap.py`: Runtime bootstrap (`.env` + DB init).
- `config.py`: Config loading.
- `config_validation.py`: Config validation rules.
- `dashboard.py`: Flask dashboard server.
- `templates/`: Dashboard HTML templates.

## Usage
- Start bot: `uv run -m app.main`
- Start dashboard: `uv run app/dashboard.py`

## Notes
Use this layer for app startup and HTTP/UI concerns, not trading logic.
