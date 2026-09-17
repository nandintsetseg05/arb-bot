"""Decimal fee engine: exact cents, and unknown Polymarket fees are rejected not guessed."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.analysis.fee_engine import kalshi_taker_fee, polymarket_taker_fee
from src.errors import FeeDataUnavailable


def test_kalshi_fee_exact_at_half() -> None:
    assert kalshi_taker_fee(100, 0.5) == Decimal("1.75")


def test_kalshi_fee_rounds_up_off_center() -> None:
    # ceil(7 * 100 * 0.45 * 0.55) = ceil(173.25) = 174 cents.
    assert kalshi_taker_fee(100, 0.45) == Decimal("1.74")


def test_kalshi_fee_zero_at_boundaries_and_bad_size() -> None:
    assert kalshi_taker_fee(100, 0.0) == Decimal("0.00")
    assert kalshi_taker_fee(100, 1.0) == Decimal("0.00")
    assert kalshi_taker_fee(0, 0.5) == Decimal("0.00")


def test_kalshi_fee_returns_decimal() -> None:
    assert isinstance(kalshi_taker_fee(100, 0.5), Decimal)


def test_polymarket_fee_with_rate() -> None:
    assert polymarket_taker_fee(100, 200) == Decimal("2.00")


def test_polymarket_fee_without_rate_rejects() -> None:
    with pytest.raises(FeeDataUnavailable):
        polymarket_taker_fee(100, None)
