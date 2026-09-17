"""SQLite persistence — telemetry + audit trail for opportunities, trades, legs."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe sqlite wrapper. One connection per process; serialized via a lock."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; explicit BEGIN/COMMIT via context manager
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, open(SCHEMA_PATH, encoding="utf-8") as f:
            self._conn.executescript(f.read())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----- inserts -----

    def insert_opportunity(self, **fields: Any) -> int:
        fields.setdefault("detected_at", _utcnow_iso())
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO opportunities ({cols}) VALUES ({placeholders})", fields
            )
            return int(cur.lastrowid or 0)

    def insert_trade(self, opportunity_id: int, mode: str, status: str = "pending") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO trades (opportunity_id, started_at, mode, status) "
                "VALUES (?, ?, ?, ?)",
                (opportunity_id, _utcnow_iso(), mode, status),
            )
            return int(cur.lastrowid or 0)

    def insert_leg(self, **fields: Any) -> int:
        fields.setdefault("submitted_at", _utcnow_iso())
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO legs ({cols}) VALUES ({placeholders})", fields
            )
            return int(cur.lastrowid or 0)

    def update_leg(self, leg_id: int, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["leg_id"] = leg_id
        with self._lock:
            self._conn.execute(f"UPDATE legs SET {sets} WHERE id = :leg_id", fields)

    def update_trade(self, trade_id: int, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["trade_id"] = trade_id
        with self._lock:
            self._conn.execute(f"UPDATE trades SET {sets} WHERE id = :trade_id", fields)

    def insert_scan_record(self, **fields: Any) -> int:
        fields.setdefault("observed_at", _utcnow_iso())
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO scan_records ({cols}) VALUES ({placeholders})", fields
            )
            return int(cur.lastrowid or 0)

    def recent_scan_records(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM scan_records ORDER BY observed_at DESC LIMIT ?", (limit,)
            )
            return cur.fetchall()

    def snapshot_balance(self, venue: str, balance_usd: float, note: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO balance_snapshots (captured_at, venue, balance_usd, note) "
                "VALUES (?, ?, ?, ?)",
                (_utcnow_iso(), venue, balance_usd, note),
            )

    # ----- reads (for dashboard + risk) -----

    def recent_opportunities(self, limit: int = 100) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM opportunities ORDER BY detected_at DESC LIMIT ?", (limit,)
            )
            return cur.fetchall()

    def recent_trades(self, limit: int = 100) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM trades ORDER BY started_at DESC LIMIT ?", (limit,)
            )
            return cur.fetchall()

    def trade_legs(self, trade_id: int) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM legs WHERE trade_id = ? ORDER BY id ASC", (trade_id,)
            )
            return cur.fetchall()

    def realized_pnl_total(self) -> float:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0.0) AS s FROM trades WHERE realized_pnl IS NOT NULL"
            )
            row = cur.fetchone()
            return float(row["s"]) if row else 0.0

    def latest_balance(self, venue: str) -> float | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT balance_usd FROM balance_snapshots WHERE venue = ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (venue,),
            )
            row = cur.fetchone()
            return float(row["balance_usd"]) if row else None

    def equity_curve(self, limit: int = 1000) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT captured_at, venue, balance_usd FROM balance_snapshots "
                "ORDER BY captured_at ASC LIMIT ?",
                (limit,),
            )
            return cur.fetchall()
