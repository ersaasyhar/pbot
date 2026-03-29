# core/services/

## Purpose
Service layer for live runtime flow.

## Key Files
- `trading_pipeline.py`: Tick ingest, feature build, signal/candidate flow.
- `event_router.py`: WebSocket event parsing/routing.
- `sync_coordinator.py`: Periodic sync loop (allowlists, gate, subscription refresh, flush/update).
- `external_context_service.py`: External BTC spot/perp context collectors + DB persistence.

## Usage
Composed by `core/engine.py`.

## Notes
Each service owns one operational responsibility.
