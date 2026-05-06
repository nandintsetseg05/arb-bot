"""Kelly criterion sizing.

For risk-free arbitrage the bet is theoretically full-bankroll, but real arbs are
*near* risk-free (partial fills, fee mis-estimation, resolution disputes). We treat
edge_bps as a probabilistic edge and apply quarter-Kelly by default.

  Kelly fraction f* = edge / variance_proxy
  We use variance_proxy = 1 (binary outcome with mean ~0.5), so f* = edge_per_unit.
  Quarter-Kelly: f = f* / 4
"""

from __future__ import annotations


def kelly_fraction(edge_per_unit: float, *, quarter: bool = True, cap: float = 0.10) -> float:
    """Return fraction of bankroll to deploy on this opportunity, capped.

    `edge_per_unit` is gross profit per dollar staked (e.g. 0.03 for 3%).
    `cap` is a hard ceiling regardless of computed Kelly.
    """
    if edge_per_unit <= 0:
        return 0.0
    f = edge_per_unit
    if quarter:
        f = f / 4.0
    return min(f, cap)


def size_usd(
    *,
    edge_per_unit: float,
    bankroll_usd: float,
    max_position_usd: float,
    quarter: bool = True,
) -> float:
    """Compute USD position size from bankroll, edge, and the per-trade hard cap."""
    f = kelly_fraction(edge_per_unit, quarter=quarter)
    raw = f * bankroll_usd
    return max(0.0, min(raw, max_position_usd, bankroll_usd))
