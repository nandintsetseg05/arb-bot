"""Common types + abstract interface for exchange clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Venue(str, Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Outcome(str, Enum):
    YES = "YES"
    NO = "NO"


@dataclass(frozen=True)
class OrderbookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class Orderbook:
    venue: Venue
    market_id: str          # Polymarket: token_id; Kalshi: ticker
    outcome: Outcome
    bids: tuple[OrderbookLevel, ...]   # descending price
    asks: tuple[OrderbookLevel, ...]   # ascending price
    fetched_at_ms: int

    @property
    def best_bid(self) -> OrderbookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> OrderbookLevel | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class Market:
    venue: Venue
    market_id: str          # Polymarket: condition_id or slug; Kalshi: ticker
    question: str
    outcomes: tuple[str, ...]   # ("Yes", "No") typical; multi-outcome possible on Polymarket
    yes_token_id: str | None = None  # Polymarket only
    no_token_id: str | None = None   # Polymarket only
    closes_at_iso: str | None = None
    category: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderRequest:
    venue: Venue
    market_id: str
    outcome: Outcome
    side: Side
    size: float          # contracts (Kalshi) / shares (Polymarket)
    price: float         # limit price 0..1 (Polymarket) or 1..99 cents (Kalshi)
    client_id: str | None = None


@dataclass(frozen=True)
class OrderResult:
    venue: Venue
    venue_order_id: str | None
    accepted: bool
    filled_size: float
    avg_fill_price: float
    fee_usd: float
    raw_response: dict[str, object]
    error: str | None = None


class BaseExchangeClient(ABC):
    venue: Venue

    @abstractmethod
    async def list_markets(self, *, active_only: bool = True) -> list[Market]: ...

    @abstractmethod
    async def get_orderbook(self, market_id: str, outcome: Outcome) -> Orderbook: ...

    @abstractmethod
    async def get_balance_usd(self) -> float: ...

    @abstractmethod
    async def place_order(self, req: OrderRequest) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, venue_order_id: str) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...
