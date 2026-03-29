# data/

## Purpose
Market-data clients plus persistence facade for the rest of the codebase.

## Key Files
- `fetcher.py`: Market discovery/fetch logic.
- `websocket_client.py`: WebSocket client wrapper.
- `clob_client.py`: CLOB client helpers.
- `data_client.py`: Data API helpers.
- `storage.py`: Stable public persistence facade.
- `db_config.py`: DB path/config constants.
- `repositories/`: Concrete SQLite repository modules.

Additional persisted context:
- `external_spot_ticks` (Binance spot book ticker-derived features)
- `perp_context_ticks` (funding/open-interest/liquidation context)

## Usage
Import `data.storage` for persistence API used by runtime/strategy.

## Notes
New persistence logic should go to `data/repositories/*` and be re-exported via `storage.py`.
