"""Walks an orderbook to compute fillable size and average fill price up to a price limit.

We never trust the top-of-book number. The matched-pair leg sizes are the *minimum*
fillable depth at acceptable price across both venues.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.clients.base import Orderbook


@dataclass(frozen=True)
class FillEstimate:
    contracts: float       # how many contracts/shares we can take
    avg_price: float       # weighted average fill price 0..1
    worst_price: float     # last level we'd touch
    notional_usd: float    # contracts * avg_price
    levels_walked: int


def walk_asks(book: Orderbook, *, max_price: float, max_notional_usd: float) -> FillEstimate:
    """Walk asks (we are buying), accumulating size while ask <= max_price and notional <= cap."""
    taken = 0.0
    spent = 0.0
    last_price = 0.0
    walked = 0
    for level in book.asks:
        if level.price > max_price:
            break
        remaining_usd = max_notional_usd - spent
        if remaining_usd <= 0:
            break
        max_take_at_level = min(level.size, remaining_usd / level.price)
        if max_take_at_level <= 0:
            break
        taken += max_take_at_level
        spent += max_take_at_level * level.price
        last_price = level.price
        walked += 1
    avg = (spent / taken) if taken > 0 else 0.0
    return FillEstimate(
        contracts=taken,
        avg_price=avg,
        worst_price=last_price,
        notional_usd=spent,
        levels_walked=walked,
    )


def walk_bids(book: Orderbook, *, min_price: float, max_size: float) -> FillEstimate:
    """Walk bids (we are selling), accumulating size while bid >= min_price."""
    taken = 0.0
    revenue = 0.0
    last_price = 1.0
    walked = 0
    for level in book.bids:
        if level.price < min_price:
            break
        remaining = max_size - taken
        if remaining <= 0:
            break
        take = min(level.size, remaining)
        taken += take
        revenue += take * level.price
        last_price = level.price
        walked += 1
    avg = (revenue / taken) if taken > 0 else 0.0
    return FillEstimate(
        contracts=taken,
        avg_price=avg,
        worst_price=last_price,
        notional_usd=revenue,
        levels_walked=walked,
    )
