# DIFFERENCES_FROM_SOURCES.md

What this repo does differently from the source repos studied during analysis. Updated as implementation progresses.

## Sources studied

- `ImMike/polymarket-arbitrage` — primary; layout, matcher shape, bundle-arb math.
- `CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot` — strike-comparison math (3 cases) borrowed as test fixtures.
- `WSOL12/Polymarket-Kalshi-Arbitrage-Trading-Bot-BTC` — confirmed near-duplicate of CarlosIbCu; nothing additional taken.

## Concrete differences

### Auth
- **ImMike:** Polymarket CLOB auth left as TODO; Kalshi client is read-only (no login).
- **Here:** Polymarket via `py-clob-client` (full L2: derived API creds + EIP-712 signed orders). Kalshi via RSA-PSS-SHA256 over `{timestamp_ms}{METHOD}{path}` with `cryptography` lib — supports demo and prod endpoints.

### Fee model
- **ImMike:** Hardcoded `kalshi_taker_fee = 0.01` (flat 1%). Wrong near $0.50 (real fee is ~1.75¢ per contract there).
- **Here:** `edge_calculator.kalshi_taker_fee_usd(contracts, price)` implements exact `ceil(0.07 * contracts * price * (1 - price))` cents formula.

### Execution timing
- **ImMike:** Sequential `asyncio.Queue` consumer — one signal at a time.
- **Here:** Cross-exchange opportunity fires `asyncio.gather(place_leg_a, place_leg_b)`, with `partial_fill_recovery` running synchronously after gather to detect/unwind.

### Persistence
- **ImMike:** In-memory dicts only; logs as text files.
- **Here:** SQLite (`opportunities`, `trades`, `legs`, `balance_snapshots`) with WAL mode; Streamlit dashboard reads directly.

### Matching
- **ImMike:** difflib `SequenceMatcher` + hardcoded NFL/NBA roster dicts + politician regex.
- **Here:** `rapidfuzz.fuzz.token_set_ratio` + generic entity overlap (capitalized tokens, dates, $-amounts) + category prefilter. No hardcoded sport rosters.
- Two-tier confidence: `≥ 0.85` auto-eligible; `0.65–0.85` logged as `review_required` and never auto-traded.

### Config surface
- **ImMike:** YAML (`config.yaml`).
- **Here:** Single `.env` via pydantic-settings. Live-trading enable requires both env flag and CLI flag.

### Retry
- **ImMike:** Hand-rolled `for attempt in range(3): ...` with multiplicative backoff.
- **Here:** `tenacity` decorators with exponential jitter; one `@retry_api_call` policy reused across both clients.

### Dashboard
- **ImMike:** FastAPI + custom HTML.
- **Here:** Streamlit `dashboard/app.py`, ~150 LOC, reads SQLite.

### CarlosIbCu strike math
- **CarlosIbCu:** Inline 3-case `if/elif/elif` in `arbitrage_bot.py:85-140` for BTC up/down vs Kalshi strike.
- **Here:** Same math lifted into `tests/test_arbitrage_math.py` as parameterised pytest fixtures. Production code in `edge_calculator.py` is general (any binary outcome pair), strike-comparison is a special case.

## Things deliberately NOT borrowed

- ImMike's `core/portfolio.py` — duplicates SQLite-based state we get for free.
- ImMike's hardcoded sport-roster dicts — narrow, stale, brittle.
- CarlosIbCu's URL-slug generation — works only for `bitcoin-up-or-down-*` markets.
- CarlosIbCu's mock backend — we use real APIs in paper mode (real prices, simulated fills).
- WSOL12 — confirmed near-fork; nothing unique.
