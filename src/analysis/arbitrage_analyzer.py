"""Combines orderbooks + matched pairs into actionable Opportunity objects.

Two detectors:
  detect_cross_exchange(matched_pair, ob_poly_yes, ob_poly_no, ob_kalshi_yes, ob_kalshi_no)
    → checks both directions (Poly_NO+Kalshi_YES and Poly_YES+Kalshi_NO),
      walks orderbooks, computes net edge, returns the better opportunity if any.

  detect_bundle(market, books)
    → for a multi-outcome market on Polymarket, checks Σ ask < 1 (long) or Σ bid > 1 (short).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from src.analysis.edge_calculator import (
    POLYMARKET_DEFAULT_TAKER_BPS,
    BundleEdge,
    bundle_long_edge,
    bundle_short_edge,
    cross_exchange_edge,
    kalshi_taker_fee_usd,
    polymarket_taker_fee_usd,
)
from src.analysis.slippage_estimator import walk_asks, walk_bids
from src.clients.base import Market, Orderbook, Outcome, Side, Venue
from src.matching.market_matcher import MatchedPair, MatchTier

logger = logging.getLogger(__name__)


class ArbType(str, Enum):
    CROSS_EXCHANGE = "cross_exchange"
    BUNDLE = "bundle"


@dataclass(frozen=True)
class OpportunityLeg:
    venue: Venue
    market_id: str
    outcome: Outcome
    side: Side
    price: float
    size: float


@dataclass(frozen=True)
class Opportunity:
    arb_type: ArbType
    detected_at_ms: int
    legs: tuple[OpportunityLeg, ...]
    gross_edge_usd: float
    fees_usd: float
    slippage_buffer_usd: float
    net_edge_usd: float
    edge_bps: int
    notional_usd: float
    confidence: float                 # 0..1; for bundle = 1.0; for cross = match score
    review_required: bool             # if matcher flagged but did not auto-clear
    poly_market: Market | None = None
    kalshi_market: Market | None = None

    def is_stale(self, ttl_ms: int, now_ms: int | None = None) -> bool:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        return now - self.detected_at_ms > ttl_ms


class ArbitrageAnalyzer:
    def __init__(
        self,
        *,
        min_edge_bps: int,
        max_position_usd: float,
        slippage_buffer_pct: float = 0.005,
    ) -> None:
        self.min_edge_bps = min_edge_bps
        self.max_position_usd = max_position_usd
        self.slippage_buffer_pct = slippage_buffer_pct

    # ------------------------------------------------------------------
    # Cross-exchange
    # ------------------------------------------------------------------

    def detect_cross_exchange(
        self,
        pair: MatchedPair,
        *,
        ob_poly_yes: Orderbook,
        ob_poly_no: Orderbook,
        ob_kalshi_yes: Orderbook,
        ob_kalshi_no: Orderbook,
    ) -> Opportunity | None:
        # Direction 1: buy YES on Polymarket, NO on Kalshi.
        opp_a = self._cross_direction(
            poly_book=ob_poly_yes,
            poly_outcome=Outcome.YES,
            kalshi_book=ob_kalshi_no,
            kalshi_outcome=Outcome.NO,
            pair=pair,
        )
        # Direction 2: buy NO on Polymarket, YES on Kalshi.
        opp_b = self._cross_direction(
            poly_book=ob_poly_no,
            poly_outcome=Outcome.NO,
            kalshi_book=ob_kalshi_yes,
            kalshi_outcome=Outcome.YES,
            pair=pair,
        )
        candidates = [o for o in (opp_a, opp_b) if o is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda o: o.net_edge_usd)

    def _cross_direction(
        self,
        *,
        poly_book: Orderbook,
        poly_outcome: Outcome,
        kalshi_book: Orderbook,
        kalshi_outcome: Outcome,
        pair: MatchedPair,
    ) -> Opportunity | None:
        if not poly_book.asks or not kalshi_book.asks:
            return None
        poly_top = poly_book.asks[0]
        kalshi_top = kalshi_book.asks[0]
        # Quick screen on tops; if 1 - a - b <= 0 give up early.
        if 1.0 - poly_top.price - kalshi_top.price <= 0:
            return None

        # Walk both books up to a price ceiling that still leaves edge after fees.
        # Cap notional at max_position_usd / 2 per leg.
        cap_per_leg = self.max_position_usd / 2.0
        # Allow walking up to leg-price + (1 - poly_top - kalshi_top)/2 to preserve edge.
        edge_per_unit = 1.0 - poly_top.price - kalshi_top.price
        poly_limit = poly_top.price + edge_per_unit / 2.0
        kalshi_limit = kalshi_top.price + edge_per_unit / 2.0

        poly_fill = walk_asks(poly_book, max_price=poly_limit, max_notional_usd=cap_per_leg)
        kalshi_fill = walk_asks(kalshi_book, max_price=kalshi_limit, max_notional_usd=cap_per_leg)
        if poly_fill.contracts <= 0 or kalshi_fill.contracts <= 0:
            return None

        # Match on contracts (same number of binary claims on each side).
        contracts = int(min(poly_fill.contracts, kalshi_fill.contracts))
        if contracts <= 0:
            return None

        poly_notional = contracts * poly_fill.avg_price
        kalshi_notional = contracts * kalshi_fill.avg_price
        poly_fee = polymarket_taker_fee_usd(poly_notional, POLYMARKET_DEFAULT_TAKER_BPS)
        kalshi_fee = kalshi_taker_fee_usd(contracts, kalshi_fill.avg_price)

        edge = cross_exchange_edge(
            leg_a_price=poly_fill.avg_price,
            leg_b_price=kalshi_fill.avg_price,
            contracts=contracts,
            leg_a_fee_usd=poly_fee,
            leg_b_fee_usd=kalshi_fee,
        )
        slip_buffer = self.slippage_buffer_pct * (poly_notional + kalshi_notional)
        net_after_buffer = edge.net_usd - slip_buffer
        notional = poly_notional + kalshi_notional
        if notional <= 0:
            return None
        bps = round(10_000 * net_after_buffer / notional)
        if bps < self.min_edge_bps:
            return None

        legs = (
            OpportunityLeg(
                venue=Venue.POLYMARKET,
                market_id=poly_book.market_id,
                outcome=poly_outcome,
                side=Side.BUY,
                price=poly_fill.avg_price,
                size=float(contracts),
            ),
            OpportunityLeg(
                venue=Venue.KALSHI,
                market_id=kalshi_book.market_id,
                outcome=kalshi_outcome,
                side=Side.BUY,
                price=kalshi_fill.avg_price,
                size=float(contracts),
            ),
        )
        return Opportunity(
            arb_type=ArbType.CROSS_EXCHANGE,
            detected_at_ms=max(poly_book.fetched_at_ms, kalshi_book.fetched_at_ms),
            legs=legs,
            gross_edge_usd=edge.gross_usd,
            fees_usd=edge.fees_usd,
            slippage_buffer_usd=slip_buffer,
            net_edge_usd=net_after_buffer,
            edge_bps=bps,
            notional_usd=notional,
            confidence=pair.score.blended,
            review_required=pair.tier is MatchTier.REVIEW,
            poly_market=pair.polymarket,
            kalshi_market=pair.kalshi,
        )

    # ------------------------------------------------------------------
    # Bundle
    # ------------------------------------------------------------------

    def detect_bundle_long(
        self,
        market: Market,
        outcome_books: Sequence[Orderbook],
    ) -> Opportunity | None:
        if len(outcome_books) < 2:
            return None
        cap = self.max_position_usd
        per_leg_cap = cap / len(outcome_books)
        fills = [walk_asks(b, max_price=1.0, max_notional_usd=per_leg_cap) for b in outcome_books]
        if any(f.contracts <= 0 for f in fills):
            return None
        contracts = int(min(f.contracts for f in fills))
        if contracts <= 0:
            return None
        prices = tuple(f.avg_price for f in fills)
        edge: BundleEdge = bundle_long_edge(asks=prices, contracts=contracts)
        notional = sum(prices) * contracts
        slip_buffer = self.slippage_buffer_pct * notional
        net_after_buffer = edge.net_usd - slip_buffer
        if notional <= 0:
            return None
        bps = round(10_000 * net_after_buffer / notional)
        if bps < self.min_edge_bps:
            return None
        legs = tuple(
            OpportunityLeg(
                venue=Venue.POLYMARKET,
                market_id=b.market_id,
                outcome=b.outcome,
                side=Side.BUY,
                price=f.avg_price,
                size=float(contracts),
            )
            for b, f in zip(outcome_books, fills, strict=False)
        )
        return Opportunity(
            arb_type=ArbType.BUNDLE,
            detected_at_ms=max(b.fetched_at_ms for b in outcome_books),
            legs=legs,
            gross_edge_usd=edge.gross_usd,
            fees_usd=edge.fees_usd,
            slippage_buffer_usd=slip_buffer,
            net_edge_usd=net_after_buffer,
            edge_bps=bps,
            notional_usd=notional,
            confidence=1.0,
            review_required=False,
            poly_market=market,
        )

    def detect_bundle_short(
        self,
        market: Market,
        outcome_books: Sequence[Orderbook],
    ) -> Opportunity | None:
        if len(outcome_books) < 2:
            return None
        cap = self.max_position_usd
        per_leg_cap = cap / len(outcome_books)
        max_size_per_leg = per_leg_cap  # rough ceiling; bid walk caps by size, not by USD
        fills = [walk_bids(b, min_price=0.0, max_size=max_size_per_leg) for b in outcome_books]
        if any(f.contracts <= 0 for f in fills):
            return None
        contracts = int(min(f.contracts for f in fills))
        if contracts <= 0:
            return None
        prices = tuple(f.avg_price for f in fills)
        edge: BundleEdge = bundle_short_edge(bids=prices, contracts=contracts)
        notional = sum(prices) * contracts
        slip_buffer = self.slippage_buffer_pct * notional
        net_after_buffer = edge.net_usd - slip_buffer
        if notional <= 0:
            return None
        bps = round(10_000 * net_after_buffer / notional)
        if bps < self.min_edge_bps:
            return None
        legs = tuple(
            OpportunityLeg(
                venue=Venue.POLYMARKET,
                market_id=b.market_id,
                outcome=b.outcome,
                side=Side.SELL,
                price=f.avg_price,
                size=float(contracts),
            )
            for b, f in zip(outcome_books, fills, strict=False)
        )
        return Opportunity(
            arb_type=ArbType.BUNDLE,
            detected_at_ms=max(b.fetched_at_ms for b in outcome_books),
            legs=legs,
            gross_edge_usd=edge.gross_usd,
            fees_usd=edge.fees_usd,
            slippage_buffer_usd=slip_buffer,
            net_edge_usd=net_after_buffer,
            edge_bps=bps,
            notional_usd=notional,
            confidence=1.0,
            review_required=False,
            poly_market=market,
        )
