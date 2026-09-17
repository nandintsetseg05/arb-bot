"""Decimal fee engine. Money math is exact (no float); unknown fees are rejected, not guessed.

Kept separate from edge_calculator.py (which keeps its float functions for existing callers)
so the crypto scanners get correct sub-cent rounding without churning tested code.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from src.errors import FeeDataUnavailable

CENT = Decimal("0.01")


def _dec(x: float | Decimal | int | str) -> Decimal:
    # Decimal(str(...)) avoids binary-float artifacts like Decimal(0.07).
    return x if isinstance(x, Decimal) else Decimal(str(x))


def kalshi_taker_fee(contracts: int, price: float | Decimal) -> Decimal:
    """Exact Kalshi taker fee in USD: ceil(0.07 * C * P * (1-P)) cents.

    Zero at the price boundaries and for non-positive size. Reference: kalshi.com/docs/fees.
    """
    p = _dec(price)
    if contracts <= 0 or not (Decimal(0) < p < Decimal(1)):
        return Decimal("0.00")
    cents = (Decimal(7) * contracts * p * (Decimal(1) - p)).to_integral_value(ROUND_CEILING)
    return (cents / Decimal(100)).quantize(CENT)


def polymarket_taker_fee(notional_usd: float | Decimal, fee_rate_bps: int | None) -> Decimal:
    """Polymarket taker fee = notional * bps / 10_000.

    Polymarket taker fees are per-market and not universally known; when the rate is
    unavailable we REJECT rather than assume a default (evidence rule).
    """
    if fee_rate_bps is None:
        raise FeeDataUnavailable("polymarket taker fee rate unknown for this market")
    return (_dec(notional_usd) * Decimal(fee_rate_bps) / Decimal(10_000)).quantize(CENT)
