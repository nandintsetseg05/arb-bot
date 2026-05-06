## What

What does this PR do? Be concise.

## Why

What problem does it solve? Link to issue if applicable.

## Risk profile

- [ ] Touches code paths used in `live_run.py`
- [ ] Modifies any of: `executor.py`, `partial_fill_recovery.py`, `circuit_breaker.py`, `position_limits.py`, fee calculations
- [ ] Changes the `LIVE_TRADING_ENABLED` gate or its dependencies
- [ ] Adds a new external API call

If any are checked: explain why the change is safe and what testing you did.

## Tests

- [ ] `pytest` passes locally (37+ tests)
- [ ] Added new tests for the new behaviour
- [ ] Did NOT relax existing tests to make them pass

## Checklist

- [ ] No secrets, keys, or `.env` content in the diff
- [ ] Updated `CHANGELOG.md` under `## [Unreleased]`
- [ ] Updated docs (`README.md`, `REFACTOR_PLAN.md`, or module docstrings) if behaviour changed
- [ ] `ruff check` clean
