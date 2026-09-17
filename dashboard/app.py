"""Streamlit dashboard — read-only over SQLite.

Shows the crypto scan evidence: every recorded opportunity, separated into the four numbers
the plan requires — observed gross gap, fee-adjusted margin, (simulated executable: pending
Phase 4/6b), and rejected candidates with reasons. Never presents theory as realized profit.

Run with:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config.settings import get_settings  # noqa: E402
from src.storage.db import Database  # noqa: E402

st.set_page_config(page_title="poly-arbitrage-bot", layout="wide")
st.title("poly-arbitrage-bot — crypto scan evidence")

settings = get_settings()
db = Database(settings.db_full_path)


def _df(rows: list) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


records = _df(db.recent_scan_records(limit=5000))

# --- Top metrics: counts by label ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Scan records", len(records))
if not records.empty and "label" in records.columns:
    counts = records["label"].value_counts()
    col2.metric("Locked", int(counts.get("locked", 0)))
    col3.metric("Relative-value", int(counts.get("relative_value", 0)))
    col4.metric("Rejected", int(counts.get("reject", 0)))

st.caption(
    "Locked = one settlement source resolves all legs (source-risk-free). "
    "Relative-value = same event, different index (e.g. CF Benchmarks vs Chainlink) — a price "
    "gap with residual risk, never arbitrage. 'Simulated executable P&L' is pending Phase 4 "
    "sequenced book capture; nothing here is realized profit."
)
st.markdown("---")

if not records.empty:
    # Exact Decimals were stored as text; coerce for display/plots only.
    for c in ("cost_per_set_usd", "fees_usd", "net_edge_usd"):
        if c in records.columns:
            records[c] = pd.to_numeric(records[c], errors="coerce")
    records["gross_usd_observed"] = (1.0 - records["cost_per_set_usd"]) * records["contracts"]

    # --- Candidates (locked / relative_value) ---
    st.subheader("Candidates — observed gap vs fee-adjusted margin")
    cand = records[records["label"] != "reject"]
    if not cand.empty:
        show = [
            "observed_at", "pair_id", "strategy", "label", "paper_decision", "contracts",
            "cost_per_set_usd", "gross_usd_observed", "fees_usd", "net_edge_usd", "mismatches",
        ]
        show = [c for c in show if c in cand.columns]
        st.dataframe(cand[show], use_container_width=True, hide_index=True)
    else:
        st.info("No locked / relative-value candidates recorded yet.")

    # --- Rejections with reasons ---
    st.subheader("Rejected candidates — with reasons")
    rej = records[records["label"] == "reject"]
    if not rej.empty:
        show = [c for c in ("observed_at", "pair_id", "strategy", "reason", "mismatches") if c in rej.columns]
        st.dataframe(rej[show], use_container_width=True, hide_index=True)
    else:
        st.info("No rejections recorded yet.")
else:
    st.info("No scan records yet. Approve a pair in contract_pairs.json and run scripts/paper_run.py.")

# --- Balance curve (still populated by snapshot_balances) ---
st.markdown("---")
st.subheader("Balance over time")
curve = _df(db.equity_curve(limit=5000))
if not curve.empty:
    curve["captured_at"] = pd.to_datetime(curve["captured_at"])
    chart = (
        alt.Chart(curve)
        .mark_line()
        .encode(x="captured_at:T", y="balance_usd:Q", color="venue:N")
        .properties(height=240)
    )
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No balance snapshots yet.")
