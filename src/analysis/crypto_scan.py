"""Registry-driven crypto scan orchestration.

Replaces title-based matching in the decision path: instead of guessing which markets are
equivalent, we only look at the human-reviewed pairs in the registry, fetch their books, and
run the intra-venue locked scan and the cross-venue (validator-gated) scan.

Outcome convention for short-window crypto: Kalshi YES = "up", NO = "down"; Polymarket
outcome_token_ids = (up_token, down_token). A cross-venue hedge buys UP on one venue and DOWN
on the other, so we check both directions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from src.analysis.crypto_scanner import (
    REJECT,
    RELATIVE_VALUE,
    ScanResult,
    scan_cross_venue,
    scan_intra_venue_locked,
)
from src.clients.base import BaseExchangeClient, Outcome, Venue
from src.registry.pair_registry import ContractPair

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanRecord:
    pair_id: str
    strategy: str          # intra_kalshi_locked | intra_poly_locked | cross_*
    result: ScanResult


def paper_decision(result: ScanResult) -> str:
    """Conservative paper decision from real numbers only — no guessed haircuts.

    'execute' is reserved for a LOCKED structure with positive net edge (the only
    source-risk-free case). A relative_value gap is recorded to observe, never executed.

    ponytail: TODO — latency-decay / partial-fill / one-leg simulation needs a *second*
    book observation to compare against; that arrives with Phase 4 sequenced capture /
    the replay engine. Until then we do not invent a fill haircut.
    """
    if result.label == REJECT:
        return "reject"
    if result.label == RELATIVE_VALUE:
        return "observe_relative_value"
    # LOCKED
    return "execute" if result.net_edge_usd > Decimal("0") else "skip_no_edge"


async def scan_pair(
    clients: dict[Venue, BaseExchangeClient],
    pair: ContractPair,
    *,
    poly_fee_bps: int | None,
    max_notional_usd: float,
) -> list[ScanRecord]:
    tokens = pair.polymarket.outcome_token_ids
    if len(tokens) < 2:
        logger.warning("pair missing polymarket tokens", extra={"pair": pair.pair_id})
        return []
    kalshi = clients[Venue.KALSHI]
    poly = clients[Venue.POLYMARKET]

    k_up, k_down, p_up, p_down = await asyncio.gather(
        kalshi.get_orderbook(pair.kalshi.market_id, Outcome.YES),
        kalshi.get_orderbook(pair.kalshi.market_id, Outcome.NO),
        poly.get_orderbook(tokens[0], Outcome.YES),
        poly.get_orderbook(tokens[1], Outcome.NO),
    )

    records: list[ScanRecord] = []

    intra_k = scan_intra_venue_locked([k_up, k_down], venue=Venue.KALSHI, max_notional_usd=max_notional_usd)
    if intra_k is not None:
        records.append(ScanRecord(pair.pair_id, "intra_kalshi_locked", intra_k))

    intra_p = scan_intra_venue_locked(
        [p_up, p_down], venue=Venue.POLYMARKET, poly_fee_bps=poly_fee_bps, max_notional_usd=max_notional_usd
    )
    if intra_p is not None:
        records.append(ScanRecord(pair.pair_id, "intra_poly_locked", intra_p))

    # Cross-venue hedges: UP on one venue, DOWN on the other.
    cross_a = scan_cross_venue(
        pair, kalshi_leg_book=k_up, poly_leg_book=p_down,
        poly_fee_bps=poly_fee_bps, max_notional_usd=max_notional_usd,
    )
    records.append(ScanRecord(pair.pair_id, "cross_kalshi_up_poly_down", cross_a))

    cross_b = scan_cross_venue(
        pair, kalshi_leg_book=k_down, poly_leg_book=p_up,
        poly_fee_bps=poly_fee_bps, max_notional_usd=max_notional_usd,
    )
    records.append(ScanRecord(pair.pair_id, "cross_kalshi_down_poly_up", cross_b))

    return records


async def scan_all(
    clients: dict[Venue, BaseExchangeClient],
    pairs: list[ContractPair],
    *,
    poly_fee_bps: int | None,
    max_notional_usd: float,
) -> list[ScanRecord]:
    """Scan every eligible pair; a failure on one pair never sinks the others."""
    out: list[ScanRecord] = []
    for pair in pairs:
        try:
            out.extend(
                await scan_pair(clients, pair, poly_fee_bps=poly_fee_bps, max_notional_usd=max_notional_usd)
            )
        except Exception:
            logger.exception("scan_pair failed", extra={"pair": pair.pair_id})
    return out
