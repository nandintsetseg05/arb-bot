"""Paper decision maps from real numbers only, and scan records persist immutably."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.analysis.crypto_scan import paper_decision
from src.analysis.crypto_scanner import LOCKED, REJECT, RELATIVE_VALUE, ScanResult
from src.storage.db import Database


def _res(label: str, net: str) -> ScanResult:
    return ScanResult(label, "reason", 10, Decimal("0.90"), Decimal("0.10"), Decimal(net))


def test_paper_decision_execute_only_for_locked_positive() -> None:
    assert paper_decision(_res(LOCKED, "1.00")) == "execute"
    assert paper_decision(_res(LOCKED, "-1.00")) == "skip_no_edge"
    assert paper_decision(_res(RELATIVE_VALUE, "1.00")) == "observe_relative_value"
    assert paper_decision(_res(REJECT, "0.00")) == "reject"


def test_scan_record_roundtrip(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    try:
        rid = db.insert_scan_record(
            pair_id="P",
            strategy="intra_kalshi_locked",
            label=LOCKED,
            paper_decision="execute",
            contracts=10,
            cost_per_set_usd="0.90",
            fees_usd="0.10",
            net_edge_usd="1.00",
            reason="x",
            mismatches="[]",
        )
        assert rid > 0
        rows = db.recent_scan_records()
        assert len(rows) == 1
        assert rows[0]["pair_id"] == "P"
        assert rows[0]["paper_decision"] == "execute"
        assert rows[0]["net_edge_usd"] == "1.00"
    finally:
        db.close()
