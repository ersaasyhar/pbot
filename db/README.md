# db/

## Purpose
Runtime database artifacts and local generated outputs.

## Key Files
- `market_v5.db` (+ `-wal`, `-shm`): SQLite runtime storage.
- `best_params.json`: Sweep results artifact.
- `.gitkeep`: Directory tracking marker.

## Usage
Read by runtime/backtest modules; usually managed automatically.

## Notes
Treat DB files as environment state, not source code.
