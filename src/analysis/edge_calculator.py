"""Pure-function edge calculations.

Cross-exchange arbitrage on the same binary event:
  Buy YES on venue A at $a, buy NO on venue B at $b.
  At resolution, exactly one leg pays $1 and the other pays $0.
  Per-share gross = (1 - a - b) USD.
  Net = gross * size - fees(A) - fees(B) - slippage_buffer.

Bundle arbitrage on a single venue with multi-outcome market:
  Σ ask_i  < $1 → buy each outcome (always pays exactly $1, edge = 1 - Σ ask).
  Σ bid_i  > $1 → sell each outcome (always pays exactly $1, edge = Σ bid - 1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- Polymarket fees ---
# Polymarket charges a per-market fee returned in `fee_rate_bps`. We approximate
# at 2% taker for sizing/screening; reconciliation uses actual fee_rate_bps from
# the order response.
POLYMARKET_DEFAULT_TAKER_BPS = 200


def polymarket_taker_fee_usd(notional_usd: float, fee_rate_bps: int = POLYMARKET_DEFAULT_TAKER_BPS) -> float:
    return notional_usd * fee_rate_bps / 10_000.0


# --- Kalshi fees ---


def kalshi_taker_fee_usd(contracts: int, price: float) -> float:
    """Exact Kalshi taker fee.

    Per https://kalshi.com/docs/fees: fee_cents = ceil(0.07 * C * P * (1 - P))
    where C is contracts, P is price in [0,1], and rounding is up to the next cent.
    Always non-negative; zero at the edges (P=0 or P=1).
    """
    if contracts <= 0 or not 0.0 < price < 1.0:
        return 0.0
    cents = math.ceil(7 * contracts * price * (1 - price))
    return cents / 100.0


# --- Cross-exchange arbitrage ---


@dataclass(frozen=True)
class CrossExchangeEdge:
    leg_a_price: float        # USD per share/contract, 0..1
    leg_b_price: float
    contracts: int            # matched count on both legs
    gross_per_unit: float     # 1 - a - b
    fee_a_usd: float
    fee_b_usd: float
    gross_usd: float
    fees_usd: float
    net_usd: float

    @property
    def edge_bps(self) -> int:
        notional = (self.leg_a_price + self.leg_b_price) * self.contracts
        if notional <= 0:
            return 0
        return round(10_000 * self.net_usd / notional)


def cross_exchange_edge(
    *,
    leg_a_price: float,
    leg_b_price: float,
    contracts: int,
    leg_a_fee_usd: float,
    leg_b_fee_usd: float,
) -> CrossExchangeEdge:
    """Generic edge for buying YES at one venue and NO at another.

    Either leg can be on either venue; the caller computes per-venue fees and
    passes them in. `contracts` is the matched count (we size the smaller side
    when liquidities differ; that's done in `slippage_estimator`).
    """
    gross_per_unit = 1.0 - leg_a_price - leg_b_price
    gross_usd = gross_per_unit * contracts
    fees_usd = leg_a_fee_usd + leg_b_fee_usd
    net_usd = gross_usd - fees_usd
    return CrossExchangeEdge(
        leg_a_price=leg_a_price,
        leg_b_price=leg_b_price,
        contracts=contracts,
        gross_per_unit=gross_per_unit,
        fee_a_usd=leg_a_fee_usd,
        fee_b_usd=leg_b_fee_usd,
        gross_usd=gross_usd,
        fees_usd=fees_usd,
        net_usd=net_usd,
    )


# --- Bundle arbitrage (intra-Polymarket) ---


@dataclass(frozen=True)
class BundleEdge:
    direction: str              # "long" (sum_ask < 1) or "short" (sum_bid > 1)
    prices: tuple[float, ...]
    contracts: int
    gross_per_bundle: float     # 1 - sum_ask  OR  sum_bid - 1
    gross_usd: float
    fees_usd: float
    net_usd: float

    @property
    def edge_bps(self) -> int:
        notional = sum(self.prices) * self.contracts
        if notional <= 0:
            return 0
        return round(10_000 * self.net_usd / notional)


def bundle_long_edge(
    *,
    asks: tuple[float, ...],
    contracts: int,
    fee_rate_bps: int = POLYMARKET_DEFAULT_TAKER_BPS,
) -> BundleEdge:
    s = sum(asks)
    gross_per_bundle = 1.0 - s
    gross_usd = gross_per_bundle * contracts
    notional = s * contracts
    fees_usd = polymarket_taker_fee_usd(notional, fee_rate_bps)
    return BundleEdge(
        direction="long",
        prices=asks,
        contracts=contracts,
        gross_per_bundle=gross_per_bundle,
        gross_usd=gross_usd,
        fees_usd=fees_usd,
        net_usd=gross_usd - fees_usd,
    )


def bundle_short_edge(
    *,
    bids: tuple[float, ...],
    contracts: int,
    fee_rate_bps: int = POLYMARKET_DEFAULT_TAKER_BPS,
) -> BundleEdge:
    s = sum(bids)
    gross_per_bundle = s - 1.0
    gross_usd = gross_per_bundle * contracts
    notional = s * contracts
    fees_usd = polymarket_taker_fee_usd(notional, fee_rate_bps)
    return BundleEdge(
        direction="short",
        prices=bids,
        contracts=contracts,
        gross_per_bundle=gross_per_bundle,
        gross_usd=gross_usd,
        fees_usd=fees_usd,
        net_usd=gross_usd - fees_usd,
    )
