"""Phase 0 safety: live trading must fail closed everywhere.

These tests assert that no live-order path can run in the crypto-research build.
"""

from __future__ import annotations

import pytest

from src.errors import LiveTradingDisabled
from src.execution.executor import ExecutionMode, Executor


def _make_executor(mode: ExecutionMode) -> Executor:
    # __init__ only stores its collaborators; the live guard never touches them,
    # so lightweight placeholders are sufficient for this unit test.
    return Executor(
        clients={},
        db=None,  # type: ignore[arg-type]
        breaker=None,  # type: ignore[arg-type]
        limits=None,  # type: ignore[arg-type]
        mode=mode,
        opportunity_ttl_ms=1500,
    )


def test_executor_live_mode_trips_guard() -> None:
    executor = _make_executor(ExecutionMode.LIVE)
    with pytest.raises(LiveTradingDisabled):
        executor._assert_live_allowed()


def test_executor_paper_mode_does_not_trip() -> None:
    executor = _make_executor(ExecutionMode.PAPER)
    # Must not raise.
    executor._assert_live_allowed()


def test_live_run_main_exits_nonzero() -> None:
    from scripts import live_run

    with pytest.raises(SystemExit) as exc:
        live_run.main()
    assert exc.value.code != 0
