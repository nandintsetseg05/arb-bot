# RUNBOOK — crypto-only paper research

Copy-paste steps to run the scanner on your machine, add a real contract pair, and read the
results. This build is **paper-only**: it fetches real prices but places **no orders** (live
trading fails closed — see [CRYPTO_REFACTOR_PLAN.md](CRYPTO_REFACTOR_PLAN.md) Phase 0).

Commands are PowerShell (Windows). Bash equivalents are noted where they differ.

---

## 1. Get the code

```powershell
git clone https://github.com/nandintsetseg05/arb-bot.git
cd arb-bot
git checkout crypto-research-refactor
```

## 2. Install (Python 3.11 or 3.12)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # bash: source .venv/bin/activate
pip install -e ".[dev]"
```

For a reproducible pinned install instead of the ranges: `pip install -r requirements.txt`
(regenerate the lock on 3.11 first if you deploy — it was compiled on 3.13).

## 3. Verify it's healthy

```powershell
pytest -q
ruff check src tests scripts dashboard
```

Expect all tests passing and ruff clean. No network or keys needed for this step.

## 4. Configure credentials

Even paper mode uses **real** exchange data (live order books + balance reads), so it needs
valid read credentials for both venues.

```powershell
copy .env.example .env               # bash: cp .env.example .env
```

Edit `.env` and set:

| Var | What |
|---|---|
| `POLYMARKET_PK` | Funding wallet private key (0x-hex EOA). |
| `KALSHI_KEY_ID` | Kalshi API access-key id. |
| `KALSHI_PRIVATE_KEY_PATH` | Absolute path to your Kalshi `.pem` (do **not** paste key contents). |
| `KALSHI_ENV` | `demo` to start, `prod` for real markets. |
| `POLYMARKET_TAKER_FEE_BPS` | Leave **unset** until you confirm the real per-market rate. Unset ⇒ Polymarket-fee candidates are rejected, never guessed. |

`.env` and `*.pem` are git-ignored — never commit them.

## 5. Add and approve a contract pair

Nothing is scanned until a pair in `contract_pairs.json` is **approved and verified**. The
shipped entry is an unverified `pending` example, so the scanner idles until you do this.

For a real BTC 15-minute pair:

1. **Find the two markets** — the Kalshi ticker (e.g. a `KXBTC…` 15-min market) and the
   Polymarket 15-min up/down market (its `conditionId` and the two `clobTokenIds`
   `[up, down]`).
2. **Confirm both settlement rules yourself** from each market's own page and update
   `docs/settlement_rules/<date>.json`. As of this writing Kalshi settles on CF Benchmarks
   and Polymarket on Chainlink — **different sources**, so this pair is *relative-value*, not
   locked arbitrage. That's expected.
3. **Fill the registry entry.** Both legs must share the exact same `asset` and UTC
   `utc_start`/`utc_end` window. Set `verified: true` on a leg **only** after you have
   personally checked its rules against the snapshot.
4. **Approve** by setting `"review_status": "approved"`.

A pair becomes eligible only when: `review_status == "approved"` **and** both legs
`verified` **and** asset + UTC window match on both legs. Anything malformed makes the loader
fail loud (it won't silently scan a bad pair).

> Reality check: a correctly-filled cross-venue BTC pair will be labelled
> `relative_value` / decision `observe_relative_value` — a price gap with residual risk, never
> "arbitrage." The only `execute` label is for an **intra-venue** locked structure (Kalshi
> YES+NO or Polymarket UP+DOWN on the *same* market) with positive net edge after fees.

## 6. Run the paper scanner

```powershell
python scripts/paper_run.py
```

It loops every `SCAN_INTERVAL_SECONDS`: snapshots balances, scans each eligible pair, and
**records every result** (locked / relative_value / reject, with reasons) to SQLite. Stop with
Ctrl+C. `scripts/live_run.py` intentionally refuses to run.

## 7. Read the results

Dashboard (separate terminal, venv active):

```powershell
streamlit run dashboard/app.py
```

Shows label counts, a candidates table (observed gap vs fee-adjusted net margin), rejections
with reasons, and the balance curve. Simulated-executable P&L is marked pending (see below).

Or query the DB directly:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/poly_arb.db'); c.row_factory=sqlite3.Row; [print(dict(r)) for r in c.execute('select observed_at,pair_id,strategy,label,paper_decision,net_edge_usd from scan_records order by observed_at desc limit 20')]"
```

(Simpler: open `data/poly_arb.db` in any SQLite viewer; the table is `scan_records`.)

## What this does NOT do yet

- **No latency / partial-fill / one-leg simulation.** A faithful fill model needs a second
  book observation to compare against; that arrives with Phase 4 (sequenced book capture) and
  the replay engine. Until then `net_edge_usd` is a depth-adjusted, fee-exact estimate at the
  scanned instant — not a claim that the trade would have filled.
- **No settlement-divergence measurement** (Phase 7) — logging how often CF Benchmarks and
  Chainlink actually disagree comes after we have continuous capture.

## Safety reminders

- Live trading is disabled and cannot be flipped on by env alone — re-enabling is a deliberate,
  gated decision (CRYPTO_REFACTOR_PLAN.md final Gate), not part of this runbook.
- Confirm the trading account's **actual** eligibility from Kalshi's Member Agreement and
  Polymarket's geoblock endpoint before ever considering live — do not infer from location, and
  never use VPN/second-account workarounds.
- Keep keys local. Never paste them into chat or commit them.
