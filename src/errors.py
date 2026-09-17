"""Project-wide exception types.

Kept dependency-free so any module (config, execution, scripts) can import it
without risking circular imports.
"""

from __future__ import annotations


class LiveTradingDisabled(RuntimeError):
    """Raised whenever a live-order path is reached in the crypto-research build.

    Phase 0 of CRYPTO_REFACTOR_PLAN.md makes live trading fail closed: the system
    is paper-only and must never place real orders. This exception is the trip wire.
    """


class FeeDataUnavailable(RuntimeError):
    """Raised when a fee cannot be computed from known inputs.

    The evidence rule forbids guessing fees: a candidate whose fee is unknown must be
    rejected, not estimated. See CRYPTO_REFACTOR_PLAN.md rule #5/#6.
    """
