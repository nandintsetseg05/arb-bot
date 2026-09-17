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
    # All Polymarket outcome token ids, in `outcomes` order. Populated for
    # multi-outcome markets so the bundle scan can fetch one book per outcome.
    outcome_token_ids: tuple[str, ...] = ()
    closes_at_iso: str | None = None
    category: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ContractSpec:
    """The settlement identity of one market leg.

    These fields ARE the rules: the settlement-equivalence validator compares two
    specs field by field, and the evidence rule forbids calling a pair "locked"
    unless every settlement field matches and `verified` is True on both sides.
    """

    venue: Venue
    asset: str                        # "BTC", "ETH"
    market_id: str                    # Kalshi ticker / Polymarket condition id
    utc_start: str                    # ISO-8601 window open
    utc_end: str                      # ISO-8601 window close
    settlement_source: str            # e.g. "CF Benchmarks", "Chainlink"
    source_instrument: str            # e.g. "BRTI", "BTC/USD TWAP"
    observation_window_seconds: int
    averaging_method: str
    comparison_operator: str          # ">=" / ">"
    tie_rule: str
    void_policy: str
    rules_snapshot_ref: str           # path/url to the retained settlement snapshot
    outcome_token_ids: tuple[str, ...] = ()  # Polymarket outcome tokens
    verified: bool = False            # confirmed from a cited source this build


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
