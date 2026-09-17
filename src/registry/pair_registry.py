"""Contract-pair registry: the explicit, human-reviewed list of crypto pairs to watch.

This replaces title-only matching from the decision path. A pair is a candidate only
when a human has reviewed both legs' settlement rules and set `review_status: approved`
in the git-tracked registry file — so eligibility is a reviewable diff, not a fuzzy score.

A pair being *eligible* means "approved to paper-simulate," NOT "risk-free arbitrage."
Whether it is locked or merely relative-value is decided separately by the
settlement-equivalence validator (Phase 3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.clients.base import ContractSpec, Venue

_VALID_STATUS = {"pending", "approved", "rejected"}

# ContractSpec fields a registry entry must supply (the rest have safe defaults).
_REQUIRED_SPEC_FIELDS = (
    "market_id",
    "utc_start",
    "utc_end",
    "settlement_source",
    "source_instrument",
    "observation_window_seconds",
    "averaging_method",
    "comparison_operator",
    "tie_rule",
    "void_policy",
    "rules_snapshot_ref",
)


class RegistryError(ValueError):
    """Malformed registry entry. Fail loud: a bad registry must never trade."""


@dataclass(frozen=True)
class ContractPair:
    pair_id: str
    asset: str
    kalshi: ContractSpec
    polymarket: ContractSpec
    review_status: str
    reviewer_note: str = ""

    def is_eligible(self) -> bool:
        """Approved by a human, both legs verified, and the same asset + UTC window."""
        return (
            self.review_status == "approved"
            and self.kalshi.verified
            and self.polymarket.verified
            and self.kalshi.asset == self.polymarket.asset == self.asset
            and self.kalshi.utc_start == self.polymarket.utc_start
            and self.kalshi.utc_end == self.polymarket.utc_end
        )


def _spec(venue: Venue, asset: str, raw: dict) -> ContractSpec:
    missing = [f for f in _REQUIRED_SPEC_FIELDS if f not in raw]
    if missing:
        raise RegistryError(f"{venue.value} leg missing fields: {missing}")
    return ContractSpec(
        venue=venue,
        asset=asset,
        market_id=str(raw["market_id"]),
        utc_start=str(raw["utc_start"]),
        utc_end=str(raw["utc_end"]),
        settlement_source=str(raw["settlement_source"]),
        source_instrument=str(raw["source_instrument"]),
        observation_window_seconds=int(raw["observation_window_seconds"]),
        averaging_method=str(raw["averaging_method"]),
        comparison_operator=str(raw["comparison_operator"]),
        tie_rule=str(raw["tie_rule"]),
        void_policy=str(raw["void_policy"]),
        rules_snapshot_ref=str(raw["rules_snapshot_ref"]),
        outcome_token_ids=tuple(str(t) for t in raw.get("outcome_token_ids", ())),
        verified=bool(raw.get("verified", False)),
    )


def _pair(raw: dict) -> ContractPair:
    for key in ("pair_id", "asset", "review_status", "kalshi", "polymarket"):
        if key not in raw:
            raise RegistryError(f"pair missing '{key}': {raw.get('pair_id', '<no id>')}")
    status = str(raw["review_status"])
    if status not in _VALID_STATUS:
        raise RegistryError(f"invalid review_status {status!r}; expected one of {_VALID_STATUS}")
    asset = str(raw["asset"])
    return ContractPair(
        pair_id=str(raw["pair_id"]),
        asset=asset,
        kalshi=_spec(Venue.KALSHI, asset, raw["kalshi"]),
        polymarket=_spec(Venue.POLYMARKET, asset, raw["polymarket"]),
        review_status=status,
        reviewer_note=str(raw.get("reviewer_note", "")),
    )


def load_registry(path: Path | str) -> list[ContractPair]:
    """Parse and validate the registry file. Raises RegistryError on any bad entry."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs = data.get("pairs", data) if isinstance(data, dict) else data
    if not isinstance(pairs, list):
        raise RegistryError("registry must be a list of pairs (or {'pairs': [...]})")
    seen: set[str] = set()
    out: list[ContractPair] = []
    for raw in pairs:
        pair = _pair(raw)
        if pair.pair_id in seen:
            raise RegistryError(f"duplicate pair_id: {pair.pair_id}")
        seen.add(pair.pair_id)
        out.append(pair)
    return out


def eligible_pairs(path: Path | str) -> list[ContractPair]:
    return [p for p in load_registry(path) if p.is_eligible()]
