"""Partial-fill recovery for cross-exchange arbitrage.

After both legs of a cross-exchange order fire concurrently, we may end up with:
  - Both filled: nothing to do.
  - Both unfilled: nothing to do (no exposure).
  - One leg filled, the other rejected/timed-out: we hold a naked position.

Recovery strategy:
  1. Cancel the unfilled leg if it's still pending (idempotent).
  2. Mark the trade as 'partial' so a human or downstream job can decide whether
     to attempt a manual unwind.

We do NOT auto-market-sell to unwind: a panic sell on Polymarket can move price
significantly on thin books and lock in worse losses than holding to resolution.
This is a deliberate conservative default; flag the position and surface it.
"""

from __future__ import annotations

import logging
from typing import Mapping

from src.clients.base import BaseExchangeClient, OrderResult, Venue
from src.storage.db import Database

logger = logging.getLogger(__name__)


async def attempt_recovery(
    *,
    clients: Mapping[Venue, BaseExchangeClient],
    db: Database,
    trade_id: int,
    leg_results: Mapping[object, OrderResult | None],
) -> None:
    accepted = [(leg, r) for leg, r in leg_results.items() if isinstance(r, OrderResult) and r.accepted]
    rejected = [leg for leg, r in leg_results.items() if not (isinstance(r, OrderResult) and r.accepted)]

    if not rejected:
        return  # both fine
    if not accepted:
        # Both legs failed; no exposure.
        logger.warning("trade had no successful legs", extra={"trade_id": trade_id})
        db.update_trade(trade_id, notes="all legs rejected")
        return

    # We are partial. Try to cancel any pending order on the rejected legs.
    for leg in rejected:
        result = leg_results.get(leg)
        if isinstance(result, OrderResult) and result.venue_order_id:
            client = clients[result.venue]
            ok = await client.cancel_order(result.venue_order_id)
            logger.warning(
                "recovery cancel",
                extra={
                    "trade_id": trade_id,
                    "venue": result.venue.value,
                    "order_id": result.venue_order_id,
                    "canceled": ok,
                },
            )

    db.update_trade(
        trade_id,
        notes="PARTIAL FILL — manual unwind required",
        status="partial",
    )
    logger.error(
        "partial fill — naked position",
        extra={
            "trade_id": trade_id,
            "filled_legs": [
                {"venue": r.venue.value, "size": r.filled_size, "price": r.avg_fill_price}
                for _, r in accepted
                if isinstance(r, OrderResult)
            ],
        },
    )
