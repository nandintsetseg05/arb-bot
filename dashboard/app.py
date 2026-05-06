"""Streamlit dashboard — read-only over SQLite.

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
st.title("poly-arbitrage-bot")

settings = get_settings()
db = Database(settings.db_full_path)


def _df(rows: list, columns: list[str] | None = None) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns or [])
    return pd.DataFrame([dict(r) for r in rows])


# --- Top metrics ---
col1, col2, col3, col4 = st.columns(4)
realized = db.realized_pnl_total()
poly_bal = db.latest_balance("polymarket")
kalshi_bal = db.latest_balance("kalshi")
opportunities = db.recent_opportunities(limit=500)
trades = db.recent_trades(limit=500)

col1.metric("Realized P&L (USD)", f"{realized:+,.2f}")
col2.metric("Polymarket balance", f"${poly_bal:,.2f}" if poly_bal is not None else "—")
col3.metric("Kalshi balance", f"${kalshi_bal:,.2f}" if kalshi_bal is not None else "—")
col4.metric("Opportunities (recent)", len(opportunities))

st.markdown("---")

# --- Equity curve ---
st.subheader("Balance over time")
curve = _df(db.equity_curve(limit=2000))
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
    st.info("No balance snapshots yet. Run paper_run.py to populate.")

# --- Recent opportunities ---
st.subheader("Recent opportunities")
opps_df = _df(opportunities)
if not opps_df.empty:
    show_cols = [
        "detected_at", "arb_type", "decision", "edge_bps", "net_edge_usd", "sized_usd",
        "leg_a_venue", "leg_a_side", "leg_a_price",
        "leg_b_venue", "leg_b_side", "leg_b_price",
        "poly_question", "kalshi_question", "similarity",
    ]
    show_cols = [c for c in show_cols if c in opps_df.columns]
    st.dataframe(opps_df[show_cols], use_container_width=True, hide_index=True)
else:
    st.info("No opportunities recorded yet.")

# --- Recent trades ---
st.subheader("Recent trades")
trades_df = _df(trades)
if not trades_df.empty:
    st.dataframe(trades_df, use_container_width=True, hide_index=True)

    selected = st.selectbox(
        "Inspect trade",
        options=trades_df["id"].tolist() if "id" in trades_df.columns else [],
        format_func=lambda i: f"trade #{i}",
    )
    if selected:
        legs = _df(db.trade_legs(int(selected)))
        st.write("**Legs**")
        st.dataframe(legs, use_container_width=True, hide_index=True)
else:
    st.info("No trades recorded yet.")
