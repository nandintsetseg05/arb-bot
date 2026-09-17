"""Registry loads, validates, and gates eligibility on human approval + verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.registry.pair_registry import (
    RegistryError,
    eligible_pairs,
    load_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _leg(**over: object) -> dict:
    leg = {
        "market_id": "M",
        "utc_start": "2026-09-17T00:00:00Z",
        "utc_end": "2026-09-17T00:15:00Z",
        "settlement_source": "CF Benchmarks",
        "source_instrument": "BRTI",
        "observation_window_seconds": 60,
        "averaging_method": "60s mean",
        "comparison_operator": ">=",
        "tie_rule": "binary",
        "void_policy": "none",
        "rules_snapshot_ref": "docs/settlement_rules/2026-09-17.json",
        "verified": True,
    }
    leg.update(over)
    return leg


def _pair(**over: object) -> dict:
    pair = {
        "pair_id": "BTC-1",
        "asset": "BTC",
        "review_status": "approved",
        "kalshi": _leg(),
        "polymarket": _leg(settlement_source="Chainlink", source_instrument="BTC/USD TWAP"),
    }
    pair.update(over)
    return pair


def _write(tmp_path: Path, pairs: list[dict]) -> Path:
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"pairs": pairs}), encoding="utf-8")
    return p


def test_shipped_registry_parses_and_is_not_eligible() -> None:
    # The committed example is pending + unverified: parses cleanly, eligible to nobody.
    path = REPO_ROOT / "contract_pairs.json"
    pairs = load_registry(path)
    assert len(pairs) == 1
    assert not pairs[0].is_eligible()
    assert eligible_pairs(path) == []


def test_approved_verified_matching_window_is_eligible(tmp_path: Path) -> None:
    path = _write(tmp_path, [_pair()])
    assert load_registry(path)[0].is_eligible()


def test_pending_is_not_eligible(tmp_path: Path) -> None:
    path = _write(tmp_path, [_pair(review_status="pending")])
    assert not load_registry(path)[0].is_eligible()


def test_unverified_leg_is_not_eligible(tmp_path: Path) -> None:
    path = _write(tmp_path, [_pair(polymarket=_leg(verified=False))])
    assert not load_registry(path)[0].is_eligible()


def test_mismatched_window_is_not_eligible(tmp_path: Path) -> None:
    path = _write(tmp_path, [_pair(polymarket=_leg(utc_end="2026-09-17T00:20:00Z"))])
    assert not load_registry(path)[0].is_eligible()


def test_missing_field_raises(tmp_path: Path) -> None:
    bad_leg = _leg()
    del bad_leg["settlement_source"]
    path = _write(tmp_path, [_pair(kalshi=bad_leg)])
    with pytest.raises(RegistryError):
        load_registry(path)


def test_bad_status_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, [_pair(review_status="yolo")])
    with pytest.raises(RegistryError):
        load_registry(path)


def test_duplicate_pair_id_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, [_pair(), _pair()])
    with pytest.raises(RegistryError):
        load_registry(path)
