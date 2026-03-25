# strategy/paper/

## Purpose
Refactored paper-trading modules with separated responsibilities.

## Key Files
- `state.py`: Portfolio state loading.
- `risk_manager.py`: Stake sizing and risk profile helpers.
- `execution_manager.py`: Entry execution flow.
- `exit_manager.py`: Exit lifecycle flow.
- `storage_adapter.py`: Boundary adapter to persistence layer.

## Usage
Re-exported through `strategy/paper_trader.py` compatibility facade.

## Notes
Keep business rules here; avoid direct DB imports outside the adapter.
