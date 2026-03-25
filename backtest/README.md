# backtest/

## Purpose
Offline evaluation, replay simulation, and parameter tuning.

## Key Files
- `runner.py`: Historical backtest from `market_prices`.
- `replay.py`: Replay backtest from `ws_ticks`.
- `walkforward.py`: Walk-forward validation/tuning.
- `sweep.py`: Grid sweep for fast calibration.
- `late_expiry.py`: Late-expiry simulation utility.
- `common.py`: Shared helpers used across backtest modules.

## Usage
- `make backtest`
- `make replay`
- `make walkforward`
- `make sweep`

## Notes
Keep reusable backtest logic in `common.py` to avoid drift across modules.
