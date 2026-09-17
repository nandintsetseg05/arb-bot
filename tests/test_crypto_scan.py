"""Registry-driven scan orchestration over a fake client (no network)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from src.analysis.crypto_scan import scan_pair
from src.clients.base import ContractSpec, Orderbook, OrderbookLevel, Outcome, Venue
from src.registry.pair_registry import ContractPair


class FakeClient:
    """Returns canned books keyed by (market_id, outcome)."""

    def __init__(self, venue: Venue, books: dict) -> None:
        self.venue = venue
        self._books = books

    async def get_orderbook(self, market_id: str, outcome: Outcome) -> Orderbook:
        asks = self._books.get((market_id, outcome), [])
        return Orderbook(
            venue=self.venue,
            market_id=market_id,
            outcome=outcome,
            bids=(),
            asks=tuple(OrderbookLevel(price=p, size=s) for p, s in asks),
            fetched_at_ms=0,
        )


def _spec(venue: Venue, **over: object) -> ContractSpec:
    base = dict(
        venue=venue, asset="BTC", market_id="K",
        utc_start="2026-09-17T00:00:00Z", utc_end="2026-09-17T00:15:00Z",
        settlement_source="CF Benchmarks", source_instrument="BRTI",
        observation_window_seconds=60, averaging_method="60s mean",
        comparison_operator=">=", tie_rule="binary", void_policy="none",
        rules_snapshot_ref="docs/settlement_rules/2026-09-17.json", verified=True,
    )
    base.update(over)
    return ContractSpec(**base)  # type: ignore[arg-type]


def _pair(tokens: tuple[str, ...] = ("U", "D")) -> ContractPair:
    return ContractPair(
        pair_id="BTC-1", asset="BTC",
        kalshi=_spec(Venue.KALSHI),
        polymarket=_spec(
            Venue.POLYMARKET, market_id="0xPM",
            settlement_source="Chainlink", source_instrument="BTC/USD TWAP",
            outcome_token_ids=tokens,
        ),
        review_status="approved",
    )


def _clients() -> dict:
    kalshi = FakeClient(Venue.KALSHI, {
        ("K", Outcome.YES): [(0.45, 100)],
        ("K", Outcome.NO): [(0.45, 100)],
    })
    poly = FakeClient(Venue.POLYMARKET, {
        ("U", Outcome.YES): [(0.50, 100)],
        ("D", Outcome.NO): [(0.50, 100)],
    })
    return {Venue.KALSHI: kalshi, Venue.POLYMARKET: poly}


def _by_strategy(records: list) -> dict:
    return {r.strategy: r.result for r in records}


def test_scan_pair_with_fee_labels_relative_value() -> None:
    records = asyncio.run(
        scan_pair(_clients(), _pair(), poly_fee_bps=200, max_notional_usd=500.0)
    )
    by = _by_strategy(records)
    assert by["intra_kalshi_locked"].label == "locked"
    assert by["intra_kalshi_locked"].net_edge_usd == Decimal("6.52")
    assert by["cross_kalshi_up_poly_down"].label == "relative_value"
    assert "settlement_source" in by["cross_kalshi_up_poly_down"].mismatches
    assert by["cross_kalshi_down_poly_up"].label == "relative_value"


def test_scan_pair_without_poly_fee_rejects_poly_paths() -> None:
    records = asyncio.run(
        scan_pair(_clients(), _pair(), poly_fee_bps=None, max_notional_usd=500.0)
    )
    by = _by_strategy(records)
    # Kalshi-only locked path still computes; anything needing a Polymarket fee rejects.
    assert by["intra_kalshi_locked"].label == "locked"
    assert by["intra_poly_locked"].label == "reject"
    assert by["cross_kalshi_up_poly_down"].label == "reject"


def test_scan_pair_missing_tokens_returns_nothing() -> None:
    records = asyncio.run(
        scan_pair(_clients(), _pair(tokens=()), poly_fee_bps=200, max_notional_usd=500.0)
    )
    assert records == []
