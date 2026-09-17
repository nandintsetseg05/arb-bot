# CRYPTO_REFACTOR_PLAN.md — evidence-first, crypto-only paper-research system

**Status:** planning. Supersedes the general-purpose direction in `REFACTOR_PLAN.md` for the
first build. This document maps our safety rules onto the *actual current code* in this repo and
divides the work into phases with file-level detail, tests, and exit criteria.

---

## 0. The permanent rules (non-negotiable)

These apply to every phase. If a rule and a feature conflict, the rule wins.

1. **Evidence rule.** Nothing is labelled `arbitrage`, `risk-free`, or `profitable` unless it is
   backed by (a) retained raw source data, (b) exact current fee inputs, (c) documented settlement
   equivalence, and (d) a reproducible calculation. Missing/uncertain data → **reject and record the
   exact reason**. Never guess.
2. **Scope.** BTC and ETH only, initially. Short-window markets (15-minute first).
3. **Paper only.** No live orders, no wallet/private keys, no trading credentials, no funding path.
   Live mode is **hard-disabled and fails closed** if invoked.
4. **Settlement-equivalence gate.** Reject a cross-venue pair if *any* material settlement condition
   differs: source provider, source instrument, observation window/timestamp, averaging method,
   comparison operator (`>` vs `>=`), tie handling, void/cancellation policy, settlement timing.
5. **Executable economics only.** Edge is computed from real order-book asks + available depth with
   synchronized timestamps and stale-book detection. **Decimal money math only** — no float for money.
6. **Immutable audit.** Store raw books, rule snapshots, fee snapshots, scanner decisions, paper
   orders, simulated fills, rejections — with source + receive timestamps.
7. **Reports separate the four numbers:** observed price gap → fee-adjusted theoretical margin →
   simulated executable P&L → rejected candidates + reasons. Theoretical margin is never shown as
   realized profit.

### Verified facts this plan is built on (re-confirm at build time; these changed in Aug 2026)
- **Kalshi crypto** settles on **CF Benchmarks** Real-Time Index (BRTI), 60-second average in the
  final minute. Source: Kalshi Help Center — Crypto Markets.
- **Polymarket 15-min up/down** settles on a **Chainlink** BTC/USD **TWAP** (60-second window),
  Up when end ≥ start. Source: Genfinity / CryptoSlate (Aug 2026 Chainlink TWAP rollout).
- ⇒ **Different index providers** (CF Benchmarks vs Chainlink) ⇒ cross-venue BTC pairs are
  **NOT locked arbitrage**. Both use a 60s window and `≥`, so the residual risk is *source
  divergence*, not method. Crypto is a clean binary (`≥` ⇒ no draw), unlike sports.
- **cutupdev/Polymarket-Kalshi-Arbitrage-Bot**: rule is `poly_up + kalshi_down < ~90¢` (or reverse),
  **places live orders**, ignores settlement source/fees/depth/slippage, **no license**. Use as a
  *structural reference only*; do not copy code.

### Three additions beyond the original brief
- **A. Intra-venue locked scanner first.** The only truly source-risk-free structure is buying both
  complementary legs on the *same* market/same settlement source (Kalshi YES+NO, or Polymarket
  UP+DOWN) when asks sum to `< $1` after fees. Build this before cross-venue.
- **B. Post-expiry divergence recorder.** After each window resolves, log the realized settlement
  value from *both* CF Benchmarks and Chainlink and count how often UP/DOWN disagree. This is the
  experiment that actually measures cross-venue risk instead of only assuming it.
- **C. Read rules from the live market page and snapshot them.** Never hard-code a settlement rule
  from a blog; capture it per-market and store the snapshot.

---

## Keep / change / remove in the current code

| Current code | Decision |
|---|---|
| `src/analysis/slippage_estimator.py` (`walk_asks`/`walk_bids`) | **Keep** — real depth walking is exactly right; add malformed/unsorted-book guards + tests. |
| `src/storage/` SQLite discipline (WAL, audit tables) | **Keep + extend** with registry/observation/rule/fee/divergence tables. |
| `src/risk/circuit_breaker.py`, `position_limits.py` | **Keep** for paper; persistence deferred (no live). |
| `tests/` structure (pytest, parametrized fixtures) | **Keep + greatly expand.** |
| `src/matching/market_matcher.py` + `fuzzy.py` (title similarity → auto-trade) | **Remove from the decision path.** Title similarity may *suggest* candidates but must NEVER make a pair eligible. Replace with an explicit **contract-pair registry + manual review**. |
| `src/execution/executor.py` `_execute_live`, `scripts/live_run.py` | **Hard-disable / fail-closed.** Keep the paper path; rewrite it into a realistic simulator. |
| `edge_calculator.py` float money math; Polymarket `fee_usd=0.0`; hard-coded 2% | **Replace** with a decimal fee adapter that stores exact inputs and rejects when fee data is unavailable. |
| `scripts/runner.py` cross-exchange + bundle loop, title-matched | **Rewrite** into a crypto-only loop driven by the registry, with two scanners (intra-venue locked, cross-venue relative-value). |
| `src/clients/base.py` `Market` (only yes/no token ids) | **Extend** with a `ContractSpec` carrying settlement metadata + all outcome token ids. |

---

## Phases

Each phase is self-contained and ends with tests + an exit criterion. Do them in order.

### Phase 0 — Safety lockdown & scope (0.5 day)
**Goal:** make it impossible to trade live before anything else.
- `src/config/settings.py`: add `assets_allowlist=["BTC","ETH"]`, `market_window="15m"`,
  `paper_only=True` (default, and the *only* honored value for now). Make `live_trading_enabled`
  ignored/forced false; add a `assert_paper_only()` that raises if any live path is reached.
- `scripts/live_run.py`: replace body with a hard `sys.exit` explaining live mode is disabled in the
  crypto-research build. `src/execution/executor.py`: `_execute_live` raises `LiveTradingDisabled`.
- **Tests:** `test_live_mode_fail_closed.py` — asserts every live entry point raises/exits.
- **Exit:** no code path can place a real order; test proves it.

### Phase 1 — Verify reality & snapshot rules (0.5 day, mostly research)
**Goal:** confirm the current 2026 API + settlement facts against primary docs, not this file.
- Confirm Kalshi crypto **series tickers** (e.g. BTC/ETH 15-min series), markets + orderbook
  endpoints, cursor pagination. Confirm Polymarket **Gamma** fields for 15-min up/down markets
  (condition id, `clobTokenIds`, `endDate`, rules text).
- Write `docs/settlement_rules/` with a saved snapshot (JSON + source URL + fetch timestamp) for each
  venue/asset/window. This is *data*, versioned in the repo.
- **Exit:** a committed rules snapshot per (venue, asset, window); any unverifiable claim marked
  `UNVERIFIED` and excluded from logic.

### Phase 2 — Data model & contract-pair registry (1–2 days)
**Goal:** replace title matching with explicit, reviewed contract specs.
- `src/clients/base.py`: add `ContractSpec` (asset, venue, market/ticker id, all outcome token ids,
  outcome mapping, UTC start/end, settlement source, instrument, window seconds, operator, averaging
  method, tie rule, void policy, rules-snapshot ref, review_status, reviewer_note). Extend `Market`
  to carry outcome token ids for multi-outcome (also fixes the known bundle-discovery bug).
- New `src/registry/pair_registry.py`: load/validate a **git-tracked JSON registry file**
  (`contract_pairs.json`) — a pair is only `ELIGIBLE` after a human sets `review_status:
  approved` and both legs are `verified`. (ponytail: a reviewable file *is* the manual-review
  workflow; no DB CRUD needed for human-curated config. DB tables are for immutable
  observations/fills only, added in Phase 4/6.)
- Rule snapshots live as JSON under `docs/settlement_rules/` (Phase 1), referenced by
  `rules_snapshot_ref` on each spec.
- **Tests:** registry load/validate; unreviewed pair is never eligible.
- **Exit:** can register a BTC 15-min pair by asset + exact UTC window; ineligible until approved.

### Phase 3 — Settlement-equivalence validator + truth table (1–2 days) ← rules core
**Goal:** the gate that decides locked vs relative-value vs reject.
- New `src/matching/settlement_equivalence.py`: compare two `ContractSpec`s field by field; produce
  `EquivalenceResult{status, mismatches[]}` where status ∈ `{LOCKED, NOT_LOCKED_ARBITRAGE, REJECT}`.
  Current BTC cross-venue ⇒ `NOT_LOCKED_ARBITRAGE, reason=source CF Benchmarks ≠ Chainlink`.
- New `src/analysis/truth_table.py`: enumerate the payout matrix for a candidate paired trade and
  confirm which index-outcome combinations pay both / one / neither leg.
- **Tests:** `test_settlement_equivalence.py` (source/instrument/window/operator/tie/void mismatches
  each force the right status); `test_truth_table.py` (both-lose branch is detected).
- **Exit:** no pair can reach the economics stage labelled "locked" unless equivalence == LOCKED.

### Phase 4 — Crypto discovery + sequenced order-book capture (2–3 days)
**Goal:** real, timestamped books for the registered pairs; immutable storage.
- `kalshi_client.py` / `polymarket_client.py`: discovery filtered to the crypto series/assets;
  fetch order books with `exchange_ts`, `received_ts`, `sequence`, `connection_state`; stale-book
  detection (`received - exchange > max_age → mark stale`). WebSocket is a later optimization —
  start with correctly-sequenced REST snapshots, but record sequence + timestamps now.
- `src/storage`: `orderbook_observations` table (immutable, append-only) + writer.
- **Tests:** book parsing incl. malformed/unsorted levels; stale detection; Kalshi YES/NO mirror math.
- **Exit:** for each registered pair, both venues' books are captured continuously with timestamps.

### Phase 5 — Executable economics: decimal fees + full-depth + two scanners (2–3 days)
**Goal:** correct money math and the actual opportunity detection.
- New `src/analysis/fee_engine.py` (Decimal): `kalshi_taker_fee` + `polymarket_taker_fee`;
  **rejects (FeeDataUnavailable) when a fee rate is unknown** rather than guessing. (ponytail:
  added *alongside* `edge_calculator.py`'s float functions rather than rewriting them, so existing
  callers/tests keep working; the float versions are retired once nothing uses them.)
- Reuse `walk_asks` for full-depth VWAP and max matched sets; sizing stays float, money is Decimal.
- New `src/analysis/crypto_scanner.py`:
  - **`scan_intra_venue_locked`** — same-venue complementary legs (`Σ ask < $1` after fees); one
    settlement source ⇒ label `locked`.
  - **`scan_cross_venue`** — gated by `validate_equivalence`; `REJECT` short-circuits, `LOCKED`
    (rare) or `relative_value` otherwise. Never labels a mismatched pair "arbitrage."
- **Tests:** decimal fee formula + rounding at boundaries; VWAP/max-pairs; scanner labelling
  (A→locked, B→relative_value), min-edge gating.
- **Exit:** every detected opportunity carries a status label + the four separated numbers.

### Phase 6a — Audit persistence + honest paper decision (DONE)
**Goal:** record the proprietary dataset; decide only from real numbers.
- `schema.sql`: `scan_records` table (immutable; money stored as TEXT = exact Decimal).
  `db.insert_scan_record` / `recent_scan_records`.
- `crypto_scan.paper_decision`: `execute` (LOCKED + net>0) / `skip_no_edge` / `observe_relative_value`
  / `reject` — no invented haircut.
- `runner.scan_once`: persists every ScanRecord (including rejects + reasons) then logs it.
- **Tests:** decision mapping + scan-record round-trip.

### Phase 6b — Latency/partial-fill simulator (DEFERRED to after Phase 4)
A faithful fill sim (latency decay, partial, one-leg exposure, stale-book) needs a *second*
book observation to compare against, which only Phase 4 sequenced capture / the replay engine
provides. Building a haircut model before then would be guessing (evidence rule). Marked with a
`ponytail:` TODO in `paper_decision`. When Phase 4 lands: add `paper_fills`/`simulated_fills`
tables and the both-fill / one-leg / partial / stale-reject / latency-decay scenarios.

### Phase 7 — Post-expiry settlement divergence recorder (1–2 days) ← the measurement
**Goal:** measure cross-venue risk empirically (addition B).
- New `src/research/settlement_divergence.py` + `settlement_outcomes` table: after each window
  resolves, fetch/record the realized CF Benchmarks and Chainlink values (or the venue-reported
  resolutions) and flag agree/disagree + magnitude.
- **Tests:** divergence flagged when the two sources imply different UP/DOWN.
- **Exit:** a running tally of "how often did the two indices disagree, and by how much."

### Phase 8 — Reports & dashboard (DONE)
- `dashboard/app.py` rewritten to read `scan_records`: label counts (locked/relative_value/reject),
  a candidates table (observed gross gap vs fee-adjusted net margin), a rejections table with
  reasons, and the balance curve. Simulated-executable P&L is shown as pending Phase 4/6b; nothing
  is presented as realized profit.
- (Not run in the sandbox — no Streamlit here; run `streamlit run dashboard/app.py`.)

### Phase 9 — CI + dependency pinning (DONE, partial)
- Repo-wide ruff now passes on the CI command (`ruff check src tests scripts dashboard`): safe
  modernizations applied; `UP042` (deliberate str+Enum) and `RUF002/003` (em-dash/× in comments)
  ignored in `pyproject.toml`.
- `requirements.txt`: pinned lockfile via pip-compile (`--extra dev`). NOTE: generated on Python
  3.13; regenerate on the 3.11 floor for production installs. CI still installs the pyproject
  ranges on 3.11/3.12 (range-breakage coverage); the lock is for reproducible installs.
- Still open: mypy is left informational (`continue-on-error`) — making it strict-blocking is a
  separate cleanup; the full test matrix (truth tables, stale-book, partial/one-leg) grows with
  Phases 4/6b.

### Gate — evaluate, then (only maybe) discuss a tiny live pilot
Run Scanners A+B in paper for a sustained, reproducible period. Only if the recorded evidence passes
the safety gates (eligibility confirmed, positive out-of-sample after fees/fills, simulator matches
reality, kill-switch tested) do we *discuss* a tiny live pilot — a separate decision, not automatic.
Expected honest outcome: cross-venue BTC is rejected as not-locked; intra-venue rarely fires after
fees. Proving that cheaply, with our own data, is a valid success.

---

## Known current-code bugs to fix along the way (from PROJECT_ASSESSMENT.md)
- Live execution reported as success even on partial/rejected legs (`executor.handle` / `_execute_live`).
  Resolved implicitly by Phase 0 (live disabled) but fix the outcome-propagation logic in the paper path.
- Bundle scan can't discover ≥3-outcome markets (`runner.scan_once` builds only yes/no token ids).
  Fixed by the multi-outcome `ContractSpec` in Phase 2.
- No tests on money-moving paths — addressed across Phases 3–9.
