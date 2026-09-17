"""Crypto scanners: intra-venue locked baseline + cross-venue relative-value labelling."""

from __future__ import annotations

from decimal import Decimal

from src.analysis.crypto_scanner import (
    LOCKED,
    REJECT,
    RELATIVE_VALUE,
    scan_cross_venue,
    scan_intra_venue_locked,
)
from src.clients.base import ContractSpec, Orderbook, OrderbookLevel, Outcome, Venue
from src.registry.pair_registry import ContractPair


def _book(venue: Venue, asks: list[tuple[float, float]]) -> Orderbook:
    return Orderbook(
        venue=venue,
        market_id="M",
        outcome=Outcome.YES,
        bids=(),
        asks=tuple(OrderbookLevel(price=p, size=s) for p, s in asks),
        fetched_at_ms=0,
    )


def _spec(venue: Venue, **over: object) -> ContractSpec:
    base = dict(
        venue=venue,
        asset="BTC",
        market_id="M",
        utc_start="2026-09-17T00:00:00Z",
        utc_end="2026-09-17T00:15:00Z",
        settlement_source="CF Benchmarks",
        source_instrument="BRTI",
        observation_window_seconds=60,
        averaging_method="60s mean",
        comparison_operator=">=",
        tie_rule="binary",
        void_policy="none",
        rules_snapshot_ref="docs/settlement_rules/2026-09-17.json",
        verified=True,
    )
    base.update(over)
    return ContractSpec(**base)  # type: ignore[arg-type]


def _pair(**poly_over: object) -> ContractPair:
    return ContractPair(
        pair_id="BTC-1",
        asset="BTC",
        kalshi=_spec(Venue.KALSHI),
        polymarket=_spec(Venue.POLYMARKET, settlement_source="Chainlink",
                         source_instrument="BTC/USD TWAP", **poly_over),
        review_status="approved",
    )


# --- intra-venue locked ---

def test_intra_kalshi_positive_net() -> None:
    books = [_book(Venue.KALSHI, [(0.45, 100)]), _book(Venue.KALSHI, [(0.45, 100)])]
    r = scan_intra_venue_locked(books, venue=Venue.KALSHI)
    assert r is not None
    assert r.label == LOCKED
    assert r.contracts == 100
    # gross (1-0.90)*100 = 10.00; fees 2 * 1.74 = 3.48; net 6.52.
    assert r.net_edge_usd == Decimal("6.52")


def test_intra_kalshi_negative_when_sum_over_one() -> None:
    books = [_book(Venue.KALSHI, [(0.55, 100)]), _book(Venue.KALSHI, [(0.55, 100)])]
    r = scan_intra_venue_locked(books, venue=Venue.KALSHI)
    assert r is not None and r.net_edge_usd < 0


def test_intra_polymarket_without_fee_rate_rejects() -> None:
    books = [_book(Venue.POLYMARKET, [(0.45, 100)]), _book(Venue.POLYMARKET, [(0.45, 100)])]
    r = scan_intra_venue_locked(books, venue=Venue.POLYMARKET, poly_fee_bps=None)
    assert r is not None and r.label == REJECT


def test_intra_polymarket_with_fee_rate() -> None:
    books = [_book(Venue.POLYMARKET, [(0.45, 100)]), _book(Venue.POLYMARKET, [(0.45, 100)])]
    r = scan_intra_venue_locked(books, venue=Venue.POLYMARKET, poly_fee_bps=200)
    assert r is not None and r.label == LOCKED
    # notional 90 * 2% = 1.80 fee; gross 10.00; net 8.20.
    assert r.net_edge_usd == Decimal("8.20")


# --- cross-venue ---

def test_cross_venue_different_source_is_relative_value() -> None:
    r = scan_cross_venue(
        _pair(),
        kalshi_leg_book=_book(Venue.KALSHI, [(0.45, 100)]),
        poly_leg_book=_book(Venue.POLYMARKET, [(0.50, 100)]),
        poly_fee_bps=200,
    )
    assert r.label == RELATIVE_VALUE
    assert "settlement_source" in r.mismatches
    # gross 5.00; fees 1.74 + 1.90 = 3.64; net 1.36.
    assert r.net_edge_usd == Decimal("1.36")


def test_cross_venue_unverified_rejects() -> None:
    r = scan_cross_venue(
        _pair(verified=False),
        kalshi_leg_book=_book(Venue.KALSHI, [(0.45, 100)]),
        poly_leg_book=_book(Venue.POLYMARKET, [(0.50, 100)]),
        poly_fee_bps=200,
    )
    assert r.label == REJECT


def test_cross_venue_fee_unavailable_rejects() -> None:
    r = scan_cross_venue(
        _pair(),
        kalshi_leg_book=_book(Venue.KALSHI, [(0.45, 100)]),
        poly_leg_book=_book(Venue.POLYMARKET, [(0.50, 100)]),
        poly_fee_bps=None,
    )
    assert r.label == REJECT
