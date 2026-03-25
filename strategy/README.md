# strategy/

## Purpose
Trading decision logic and paper-trading execution stack.

## Key Files
- `signal.py`: Signal generation.
- `scorer.py`: Scoring helpers.
- `paper_trader.py`: Backward-compatible facade.
- `paper/`: Refactored paper-trading modules.

## Usage
Runtime imports `strategy.signal` and `strategy.paper_trader`.

## Notes
For new paper-trading work, edit `strategy/paper/*` modules.
