"""Settlement-equivalence: locked only on identical verified rules; source diff => relative value."""

from __future__ import annotations

from src.clients.base import ContractSpec, Venue
from src.matching.settlement_equivalence import (
    EquivalenceStatus,
    validate_equivalence,
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


def test_identical_verified_specs_are_locked() -> None:
    r = validate_equivalence(_spec(Venue.KALSHI), _spec(Venue.POLYMARKET))
    assert r.status is EquivalenceStatus.LOCKED
    assert r.both_legs_can_lose is False


def test_different_source_is_relative_value_not_arbitrage() -> None:
    # The real BTC case: CF Benchmarks vs Chainlink.
    k = _spec(Venue.KALSHI)
    p = _spec(Venue.POLYMARKET, settlement_source="Chainlink", source_instrument="BTC/USD TWAP")
    r = validate_equivalence(k, p)
    assert r.status is EquivalenceStatus.NOT_LOCKED_ARBITRAGE
    assert "settlement_source" in r.mismatches
    assert r.both_legs_can_lose is True


def test_operator_mismatch_breaks_locked() -> None:
    r = validate_equivalence(_spec(Venue.KALSHI), _spec(Venue.POLYMARKET, comparison_operator=">"))
    assert r.status is EquivalenceStatus.NOT_LOCKED_ARBITRAGE
    assert "comparison_operator" in r.mismatches


def test_unverified_leg_is_rejected() -> None:
    r = validate_equivalence(_spec(Venue.KALSHI), _spec(Venue.POLYMARKET, verified=False))
    assert r.status is EquivalenceStatus.REJECT
    assert "verified" in r.mismatches


def test_different_window_is_rejected() -> None:
    r = validate_equivalence(
        _spec(Venue.KALSHI), _spec(Venue.POLYMARKET, utc_end="2026-09-17T00:20:00Z")
    )
    assert r.status is EquivalenceStatus.REJECT
    assert "utc_end" in r.mismatches


def test_different_asset_is_rejected() -> None:
    r = validate_equivalence(_spec(Venue.KALSHI), _spec(Venue.POLYMARKET, asset="ETH"))
    assert r.status is EquivalenceStatus.REJECT
    assert "asset" in r.mismatches
