# backtest/

## Purpose
Offline evaluation, replay simulation, and parameter tuning.

## Key Files
- `runner.py`: Historical backtest from `market_prices`.
- `replay.py`: Replay backtest from `ws_ticks`.
- `walkforward.py`: Walk-forward validation/tuning.
- `ab_compare.py`: A/B replay comparison between two profiles.
- `sweep.py`: Grid sweep for fast calibration.
- `late_expiry.py`: Late-expiry simulation utility.
- `common.py`: Shared helpers used across backtest modules.

## Usage
- `make backtest`
- `make replay`
- `make replay-ab`
- `make walkforward`
- `make sweep`

## Notes
Keep reusable backtest logic in `common.py` to avoid drift across modules.

`replay.py` now includes built-in diagnostics:
- resolved alignment rate
- SL saved-loss vs cut-winner impact
- setup-level expectancy
