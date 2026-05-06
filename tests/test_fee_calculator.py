"""Kalshi taker-fee formula tests at boundary prices.

Reference formula: fee_cents = ceil(0.07 * contracts * price * (1 - price))
"""

from __future__ import annotations

import math

import pytest

from src.analysis.edge_calculator import (
    POLYMARKET_DEFAULT_TAKER_BPS,
    kalshi_taker_fee_usd,
    polymarket_taker_fee_usd,
)


@pytest.mark.parametrize(
    "contracts,price,expected_cents",
    [
        # boundary: zero price → no fee
        (100, 0.0, 0),
        (100, 1.0, 0),
        # symmetric: $0.50 is the maximum
        (100, 0.5, math.ceil(7 * 100 * 0.5 * 0.5)),       # = 175 cents
        # off-center prices
        (100, 0.3, math.ceil(7 * 100 * 0.3 * 0.7)),       # ceil(147) = 147
        (100, 0.9, math.ceil(7 * 100 * 0.9 * 0.1)),       # ceil(63)  = 63
        # small size: minimum 1 cent due to ceil
        (1, 0.5, math.ceil(7 * 1 * 0.5 * 0.5)),           # ceil(1.75) = 2
        (1, 0.99, math.ceil(7 * 1 * 0.99 * 0.01)),        # ceil(0.0693) = 1
        # large size, mid: 1000 contracts at $0.50
        (1000, 0.5, math.ceil(7 * 1000 * 0.5 * 0.5)),      # 1750
    ],
)
def test_kalshi_fee_formula(contracts: int, price: float, expected_cents: int) -> None:
    fee = kalshi_taker_fee_usd(contracts, price)
    assert fee == pytest.approx(expected_cents / 100.0, abs=1e-9)


def test_kalshi_fee_invalid_inputs() -> None:
    assert kalshi_taker_fee_usd(0, 0.5) == 0.0
    assert kalshi_taker_fee_usd(-5, 0.5) == 0.0
    # Price exactly 0 or 1 → no risk → no fee.
    assert kalshi_taker_fee_usd(100, 0.0) == 0.0
    assert kalshi_taker_fee_usd(100, 1.0) == 0.0


def test_kalshi_fee_systematic_underestimation_vs_flat_one_percent() -> None:
    """ImMike's hardcoded 1% is wrong near $0.50.

    At 100 contracts × $0.50, the real fee is $1.75. The flat-1% approximation
    would give 0.01 * 100 * 0.50 = $0.50 — under-counted by $1.25.
    """
    real = kalshi_taker_fee_usd(100, 0.5)
    flat = 0.01 * 100 * 0.5
    assert real > flat * 3.0  # real is at least 3× the flat approximation here


def test_polymarket_fee_at_default_rate() -> None:
    fee = polymarket_taker_fee_usd(100.0)
    assert fee == pytest.approx(100.0 * POLYMARKET_DEFAULT_TAKER_BPS / 10_000.0)


def test_polymarket_fee_zero_notional() -> None:
    assert polymarket_taker_fee_usd(0.0) == 0.0
