"""Arbitrage math tests.

Includes the canonical 3-case strike comparison from CarlosIbCu/arbitrage_bot.py:
  Case 1: poly_strike > kalshi_strike  → buy Poly DOWN + Kalshi YES
  Case 2: poly_strike < kalshi_strike  → buy Poly UP + Kalshi NO
  Case 3: poly_strike == kalshi_strike → either complementary pair if its sum < 1.0

For our generic engine, this maps to: leg_a + leg_b < 1.0 → arb exists; per-unit
profit = 1 - leg_a - leg_b; total profit = (1 - a - b) * contracts - fees.
"""

from __future__ import annotations

import pytest

from src.analysis.edge_calculator import (
    bundle_long_edge,
    bundle_short_edge,
    cross_exchange_edge,
    kalshi_taker_fee_usd,
    polymarket_taker_fee_usd,
)

# ----------------------------------------------------------------------
# Cross-exchange (binary)
# ----------------------------------------------------------------------


def test_cross_exchange_simple_profit() -> None:
    # Trump 2024: Polymarket NO at $0.38, Kalshi YES at $0.59 → 1 - 0.97 = $0.03/unit.
    result = cross_exchange_edge(
        leg_a_price=0.38,
        leg_b_price=0.59,
        contracts=100,
        leg_a_fee_usd=0.0,
        leg_b_fee_usd=0.0,
    )
    assert result.gross_per_unit == pytest.approx(0.03)
    assert result.gross_usd == pytest.approx(3.0)
    assert result.net_usd == pytest.approx(3.0)


def test_cross_exchange_zero_edge_when_prices_sum_to_one() -> None:
    result = cross_exchange_edge(
        leg_a_price=0.45,
        leg_b_price=0.55,
        contracts=100,
        leg_a_fee_usd=0.0,
        leg_b_fee_usd=0.0,
    )
    assert result.gross_per_unit == pytest.approx(0.0)
    assert result.net_usd == pytest.approx(0.0)


def test_cross_exchange_negative_edge_when_overpriced() -> None:
    # Sum of legs > 1.0 ⇒ negative gross.
    result = cross_exchange_edge(
        leg_a_price=0.55,
        leg_b_price=0.55,
        contracts=100,
        leg_a_fee_usd=0.0,
        leg_b_fee_usd=0.0,
    )
    assert result.gross_per_unit == pytest.approx(-0.10)
    assert result.gross_usd == pytest.approx(-10.0)


def test_cross_exchange_with_realistic_fees_eats_edge() -> None:
    """3¢/unit gross can be entirely consumed by Polymarket 2% + Kalshi formula at $0.50."""
    # 100 contracts at $0.50 each leg → notional $50/leg → Polymarket fee $1, Kalshi fee $1.75
    poly_fee = polymarket_taker_fee_usd(50.0)        # $1.00
    kalshi_fee = kalshi_taker_fee_usd(100, 0.50)      # $1.75
    result = cross_exchange_edge(
        leg_a_price=0.49,
        leg_b_price=0.49,
        contracts=100,
        leg_a_fee_usd=poly_fee,
        leg_b_fee_usd=kalshi_fee,
    )
    # gross = (1 - 0.98) * 100 = $2; fees ≈ $2.75; net negative.
    assert result.gross_usd == pytest.approx(2.0)
    assert result.fees_usd == pytest.approx(poly_fee + kalshi_fee)
    assert result.net_usd < 0


def test_cross_exchange_edge_bps() -> None:
    result = cross_exchange_edge(
        leg_a_price=0.38,
        leg_b_price=0.59,
        contracts=100,
        leg_a_fee_usd=0.0,
        leg_b_fee_usd=0.0,
    )
    # net $3 / notional $97 → 309 bps
    assert result.edge_bps == 309


# ----------------------------------------------------------------------
# CarlosIbCu 3-case strike fixtures (lifted as test cases)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "case,poly_down,kalshi_yes,expected_profit",
    [
        # Case 1: poly_strike > kalshi_strike  → BUY Poly DOWN + Kalshi YES
        ("poly_gt_kalshi", 0.35, 0.55, 0.10),
        ("poly_gt_kalshi", 0.40, 0.45, 0.15),
        # No arb (sum >= 1.0)
        ("poly_gt_kalshi_no_arb", 0.50, 0.55, -0.05),
    ],
)
def test_strike_case_poly_gt_kalshi(case: str, poly_down: float, kalshi_yes: float, expected_profit: float) -> None:
    r = cross_exchange_edge(
        leg_a_price=poly_down,
        leg_b_price=kalshi_yes,
        contracts=1,
        leg_a_fee_usd=0,
        leg_b_fee_usd=0,
    )
    assert r.gross_per_unit == pytest.approx(expected_profit)


@pytest.mark.parametrize(
    "poly_up,kalshi_no,expected_profit",
    [
        (0.30, 0.50, 0.20),
        (0.45, 0.50, 0.05),
        (0.60, 0.50, -0.10),  # no arb
    ],
)
def test_strike_case_poly_lt_kalshi(poly_up: float, kalshi_no: float, expected_profit: float) -> None:
    r = cross_exchange_edge(
        leg_a_price=poly_up,
        leg_b_price=kalshi_no,
        contracts=1,
        leg_a_fee_usd=0,
        leg_b_fee_usd=0,
    )
    assert r.gross_per_unit == pytest.approx(expected_profit)


def test_strike_case_equal_strikes_both_pairs_checked() -> None:
    # When strikes are equal, both pairs are valid candidates: pick the better.
    pair1 = cross_exchange_edge(
        leg_a_price=0.40, leg_b_price=0.55, contracts=1, leg_a_fee_usd=0, leg_b_fee_usd=0
    )
    pair2 = cross_exchange_edge(
        leg_a_price=0.45, leg_b_price=0.45, contracts=1, leg_a_fee_usd=0, leg_b_fee_usd=0
    )
    assert pair1.gross_per_unit == pytest.approx(0.05)
    assert pair2.gross_per_unit == pytest.approx(0.10)
    assert pair2.gross_per_unit > pair1.gross_per_unit


# ----------------------------------------------------------------------
# Bundle (intra-Polymarket multi-outcome)
# ----------------------------------------------------------------------


def test_bundle_long_when_asks_sum_to_less_than_one() -> None:
    # 3-outcome market with asks 0.30, 0.30, 0.30 → bundle costs $0.90 → $0.10/bundle.
    edge = bundle_long_edge(asks=(0.30, 0.30, 0.30), contracts=10, fee_rate_bps=0)
    assert edge.gross_per_bundle == pytest.approx(0.10)
    assert edge.gross_usd == pytest.approx(1.0)
    assert edge.net_usd == pytest.approx(1.0)


def test_bundle_long_no_edge_when_asks_sum_to_one() -> None:
    edge = bundle_long_edge(asks=(0.50, 0.50), contracts=100, fee_rate_bps=0)
    assert edge.gross_per_bundle == pytest.approx(0.0)


def test_bundle_long_fees_reduce_net() -> None:
    edge = bundle_long_edge(asks=(0.30, 0.30, 0.30), contracts=10, fee_rate_bps=200)
    notional = 0.90 * 10  # $9
    expected_fee = notional * 200 / 10_000  # $0.18
    assert edge.fees_usd == pytest.approx(expected_fee)
    assert edge.net_usd == pytest.approx(1.0 - expected_fee)


def test_bundle_short_when_bids_sum_to_more_than_one() -> None:
    edge = bundle_short_edge(bids=(0.55, 0.55), contracts=10, fee_rate_bps=0)
    assert edge.gross_per_bundle == pytest.approx(0.10)
    assert edge.gross_usd == pytest.approx(1.0)
