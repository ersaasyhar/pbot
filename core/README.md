# core/

## Purpose
Live runtime orchestration and shared runtime/strategy helpers.

## Key Files
- `engine.py`: Thin runtime wiring/bootstrap.
- `runtime_state.py`: Shared mutable runtime state.
- `strategy_utils.py`: Runtime strategy helpers.
- `market_registry.py`: Active market registry/update logic.
- `services/`: Service modules for runtime flow.

## Usage
Used by `app/main.py` to run the live engine.

## Notes
Keep `engine.py` thin; put business flow in `core/services/*`.
