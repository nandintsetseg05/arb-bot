"""Equity-drawdown circuit breaker.

Tracks peak equity since reset, and trips when drawdown from peak exceeds the
configured threshold. Once tripped, ALL new orders are rejected until manual
reset (operator intervention).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class _State:
    peak_equity: float = 0.0
    tripped: bool = False
    trip_reason: str | None = None


class CircuitBreaker:
    def __init__(self, *, drawdown_limit: float = 0.15) -> None:
        if not 0 < drawdown_limit < 1:
            raise ValueError("drawdown_limit must be in (0, 1)")
        self.drawdown_limit = drawdown_limit
        self._state = _State()
        self._lock = threading.Lock()

    def update_equity(self, equity_usd: float) -> None:
        with self._lock:
            if equity_usd > self._state.peak_equity:
                self._state.peak_equity = equity_usd
                return
            if self._state.peak_equity <= 0:
                return
            dd = 1.0 - (equity_usd / self._state.peak_equity)
            if dd >= self.drawdown_limit and not self._state.tripped:
                self._state.tripped = True
                self._state.trip_reason = f"drawdown {dd:.2%} >= {self.drawdown_limit:.2%}"
                logger.error(
                    "circuit breaker tripped",
                    extra={
                        "peak": self._state.peak_equity,
                        "current": equity_usd,
                        "drawdown": dd,
                    },
                )

    def trip_manual(self, reason: str) -> None:
        with self._lock:
            if not self._state.tripped:
                self._state.tripped = True
                self._state.trip_reason = reason
                logger.error("circuit breaker tripped manually", extra={"reason": reason})

    def reset(self) -> None:
        with self._lock:
            self._state = _State()

    @property
    def is_tripped(self) -> bool:
        with self._lock:
            return self._state.tripped

    @property
    def trip_reason(self) -> str | None:
        with self._lock:
            return self._state.trip_reason

    @property
    def peak_equity(self) -> float:
        with self._lock:
            return self._state.peak_equity
