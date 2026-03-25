# data/repositories/

## Purpose
Concrete SQLite repository layer (single responsibility per module).

## Key Files
- `schema_repository.py`: Schema initialization and DB bootstrap.
- `market_repository.py`: Market/WS tick read-write operations.
- `portfolio_repository.py`: Portfolio/trade lifecycle persistence.
- `trade_repository.py`: Trade row mapping and trade-id helpers.
- `migration_repository.py`: Legacy JSON to SQLite migration.

## Usage
Used through `data/storage.py` facade by runtime and strategy modules.

## Notes
Keep SQL concentrated here; avoid embedding SQL in higher layers.
