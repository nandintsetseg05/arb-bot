"""Crypto scanners: the intra-venue LOCKED baseline and the cross-venue relative-value scan.

Two structures, deliberately kept apart because their risk is different:

- Intra-venue LOCKED: buy every complementary outcome on ONE market/one settlement source
  (Kalshi YES+NO, or Polymarket UP+DOWN). One source resolves all legs, so a complete set
  pays exactly $1 — no source-divergence risk. This is the only truly locked structure.

- Cross-venue: gated by the settlement-equivalence validator. Same-source pairs would be
  LOCKED (rare); the real Kalshi-vs-Polymarket BTC case is NOT_LOCKED_ARBITRAGE and is
  labelled relative_value — a price gap with residual risk, never "arbitrage".

ponytail: order-book *sizing* stays float (walk_asks); only the *money* (fees, net edge) is
Decimal, because that is where sub-cent rounding decides win/lose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from src.analysis.fee_engine import _dec, kalshi_taker_fee, polymarket_taker_fee
from src.analysis.slippage_estimator import walk_asks
from src.clients.base import Orderbook, Venue
from src.errors import FeeDataUnavailable
from src.matching.settlement_equivalence import EquivalenceStatus, validate_equivalence
from src.registry.pair_registry import ContractPair

# Result labels (superset of EquivalenceStatus, plus the intra-venue "locked").
LOCKED = "locked"
RELATIVE_VALUE = "relative_value"
REJECT = "reject"


@dataclass(frozen=True)
class ScanResult:
    label: str                       # locked | relative_value | reject
    reason: str
    contracts: int
    cost_per_set_usd: Decimal        # Σ avg ask price per complete set
    fees_usd: Decimal
    net_edge_usd: Decimal            # gross - fees; may be negative
    mismatches: tuple[str, ...] = field(default_factory=tuple)


def _reject(reason: str, mismatches: tuple[str, ...] = ()) -> ScanResult:
    return ScanResult(REJECT, reason, 0, Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), mismatches)


def scan_intra_venue_locked(
    books: Sequence[Orderbook],
    *,
    venue: Venue,
    poly_fee_bps: int | None = None,
    max_notional_usd: float = 500.0,
) -> ScanResult | None:
    """Locked scan on one venue: buy all complementary outcome books; a set always pays $1.

    Returns None when the legs can't be filled. On a Polymarket book with no known fee rate
    it returns a REJECT result (never guesses the fee).
    """
    if len(books) < 2:
        return None
    per_leg_cap = max_notional_usd / len(books)
    fills = [walk_asks(b, max_price=1.0, max_notional_usd=per_leg_cap) for b in books]
    if any(f.contracts <= 0 for f in fills):
        return None
    contracts = int(min(f.contracts for f in fills))
    if contracts <= 0:
        return None

    cost_per_set = sum((_dec(f.avg_price) for f in fills), Decimal("0"))
    gross = (Decimal(1) - cost_per_set) * contracts
    try:
        if venue is Venue.KALSHI:
            fees = sum((kalshi_taker_fee(contracts, f.avg_price) for f in fills), Decimal("0.00"))
        else:
            notional = cost_per_set * contracts
            fees = polymarket_taker_fee(notional, poly_fee_bps)
    except FeeDataUnavailable as exc:
        return _reject(str(exc))
    return ScanResult(
        label=LOCKED,
        reason="single settlement source; complete set pays $1",
        contracts=contracts,
        cost_per_set_usd=cost_per_set,
        fees_usd=fees,
        net_edge_usd=gross - fees,
    )


def scan_cross_venue(
    pair: ContractPair,
    *,
    kalshi_leg_book: Orderbook,
    poly_leg_book: Orderbook,
    poly_fee_bps: int | None = None,
    max_notional_usd: float = 500.0,
) -> ScanResult:
    """Cross-venue scan for one complementary pairing (e.g. Kalshi UP + Polymarket DOWN).

    The settlement-equivalence validator decides the label; REJECT short-circuits before any
    edge math. NOT_LOCKED pairs are labelled relative_value — a gap, never arbitrage.
    """
    eq = validate_equivalence(pair.kalshi, pair.polymarket)
    if eq.status is EquivalenceStatus.REJECT:
        return _reject(eq.reason, eq.mismatches)

    cap = max_notional_usd / 2.0
    kf = walk_asks(kalshi_leg_book, max_price=1.0, max_notional_usd=cap)
    pf = walk_asks(poly_leg_book, max_price=1.0, max_notional_usd=cap)
    if kf.contracts <= 0 or pf.contracts <= 0:
        return _reject("one or both legs unfillable")
    contracts = int(min(kf.contracts, pf.contracts))
    if contracts <= 0:
        return _reject("no matched depth")

    cost_per_set = _dec(kf.avg_price) + _dec(pf.avg_price)
    gross = (Decimal(1) - cost_per_set) * contracts
    try:
        fees = kalshi_taker_fee(contracts, kf.avg_price) + polymarket_taker_fee(
            cost_per_set * contracts, poly_fee_bps
        )
    except FeeDataUnavailable as exc:
        return _reject(str(exc), eq.mismatches)

    label = LOCKED if eq.status is EquivalenceStatus.LOCKED else RELATIVE_VALUE
    return ScanResult(
        label=label,
        reason=eq.reason,
        contracts=contracts,
        cost_per_set_usd=cost_per_set,
        fees_usd=fees,
        net_edge_usd=gross - fees,
        mismatches=eq.mismatches,
    )
