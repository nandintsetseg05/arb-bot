"""Per-market and global position-size caps.

Wraps an in-memory tally of open exposure. Trades adjust the tally on submit and
on settle. Caller resolves caps before sending orders.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    reason: str | None
    cap_remaining_usd: float


class PositionLimits:
    def __init__(
        self,
        *,
        max_per_market_usd: float,
        max_global_usd: float,
    ) -> None:
        self.max_per_market_usd = max_per_market_usd
        self.max_global_usd = max_global_usd
        self._exposure: dict[str, float] = defaultdict(float)
        self._global: float = 0.0
        self._lock = threading.Lock()

    def check(self, *, market_key: str, requested_usd: float) -> LimitDecision:
        with self._lock:
            per_market_remaining = self.max_per_market_usd - self._exposure[market_key]
            global_remaining = self.max_global_usd - self._global
            cap = min(per_market_remaining, global_remaining)
            if requested_usd > per_market_remaining:
                return LimitDecision(
                    allowed=False,
                    reason=(
                        f"per-market cap: requested ${requested_usd:.2f} but only "
                        f"${per_market_remaining:.2f} remains for {market_key}"
                    ),
                    cap_remaining_usd=max(0.0, cap),
                )
            if requested_usd > global_remaining:
                return LimitDecision(
                    allowed=False,
                    reason=(
                        f"global cap: requested ${requested_usd:.2f} but only "
                        f"${global_remaining:.2f} remains globally"
                    ),
                    cap_remaining_usd=max(0.0, cap),
                )
            return LimitDecision(allowed=True, reason=None, cap_remaining_usd=cap)

    def reserve(self, *, market_key: str, amount_usd: float) -> None:
        with self._lock:
            self._exposure[market_key] += amount_usd
            self._global += amount_usd

    def release(self, *, market_key: str, amount_usd: float) -> None:
        with self._lock:
            self._exposure[market_key] = max(0.0, self._exposure[market_key] - amount_usd)
            self._global = max(0.0, self._global - amount_usd)

    @property
    def global_exposure_usd(self) -> float:
        with self._lock:
            return self._global
