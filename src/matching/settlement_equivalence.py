"""Settlement-equivalence validator: decides locked vs relative-value vs reject.

This is the gate that enforces the evidence rule. Given two ContractSpec legs it returns:

  LOCKED               — same event, both verified, every settlement field identical.
                         One settlement source resolves both legs the same way, so a
                         complementary paired position cannot have both legs lose.
  NOT_LOCKED_ARBITRAGE — same event + both verified, but one or more settlement fields
                         differ (e.g. CF Benchmarks vs Chainlink). May be observed as a
                         relative-value candidate; MUST NEVER be called arbitrage, because
                         the two sources can disagree and both legs can lose.
  REJECT               — cannot be assessed at all: different event (asset/window), or a
                         leg is unverified. Not even a relative-value candidate.

Current Kalshi (CF Benchmarks) vs Polymarket (Chainlink) short-window BTC pairs land in
NOT_LOCKED_ARBITRAGE by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.clients.base import ContractSpec

# Settlement fields whose disagreement breaks "locked" (any diff => relative value).
_SETTLEMENT_FIELDS = (
    "settlement_source",
    "source_instrument",
    "observation_window_seconds",
    "averaging_method",
    "comparison_operator",
    "tie_rule",
    "void_policy",
)


class EquivalenceStatus(str, Enum):
    LOCKED = "locked"
    NOT_LOCKED_ARBITRAGE = "not_locked_arbitrage"
    REJECT = "reject"


@dataclass(frozen=True)
class EquivalenceResult:
    status: EquivalenceStatus
    mismatches: tuple[str, ...]
    reason: str

    @property
    def is_locked(self) -> bool:
        return self.status is EquivalenceStatus.LOCKED

    @property
    def both_legs_can_lose(self) -> bool:
        # Only a LOCKED pair (single settlement source) is safe from both-lose.
        return self.status is not EquivalenceStatus.LOCKED


def validate_equivalence(a: ContractSpec, b: ContractSpec) -> EquivalenceResult:
    # 1. Same event? Different asset or window => not comparable at all.
    identity = [
        f for f in ("asset", "utc_start", "utc_end") if getattr(a, f) != getattr(b, f)
    ]
    if identity:
        return EquivalenceResult(
            EquivalenceStatus.REJECT, tuple(identity), f"different event: {identity}"
        )

    # 2. Can we trust the rules on both sides?
    if not (a.verified and b.verified):
        return EquivalenceResult(
            EquivalenceStatus.REJECT, ("verified",), "one or both legs unverified"
        )

    # 3. Same event, both verified: locked only if every settlement field matches.
    mismatches = tuple(
        f for f in _SETTLEMENT_FIELDS if getattr(a, f) != getattr(b, f)
    )
    if not mismatches:
        return EquivalenceResult(EquivalenceStatus.LOCKED, (), "settlement fields identical")
    return EquivalenceResult(
        EquivalenceStatus.NOT_LOCKED_ARBITRAGE,
        mismatches,
        f"settlement mismatch (relative-value only): {list(mismatches)}",
    )
