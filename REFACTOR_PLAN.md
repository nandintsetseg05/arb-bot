# REFACTOR_PLAN.md — poly-arbitrage-bot

Live-grade prediction-market arbitrage bot. Two strategies in scope:

1. **Cross-exchange** — same event listed on Polymarket and Kalshi with mispriced legs.
2. **Intra-Polymarket bundle** — multi-outcome market where `Σ ask(i) < $1` (or `Σ bid(i) > $1` for the short side).

Defaults to paper mode. Live mode is gated by both env flag and runtime check.

---

## Architecture

```
                ┌────────────┐    ┌────────────┐
                │ Polymarket │    │   Kalshi   │
                │  CLOB API  │    │  REST API  │
                └─────┬──────┘    └─────┬──────┘
                      │                 │
                ┌─────▼──────┐    ┌─────▼──────┐
                │polymarket_ │    │  kalshi_   │
                │  client.py │    │ client.py  │
                └─────┬──────┘    └─────┬──────┘
                      │   (BaseExchangeClient)
                      └────────┬────────┘
                               │
                  ┌────────────▼────────────┐
                  │   matching.market_      │
                  │       matcher           │  ← rapidfuzz + entity overlap
                  └────────────┬────────────┘
                               │
                  ┌────────────▼────────────┐
                  │ analysis.arbitrage_     │
                  │       analyzer          │  ← edge_calc + slippage_est
                  └────────────┬────────────┘
                               │ Opportunity
                  ┌────────────▼────────────┐
                  │      risk gate          │  ← circuit_breaker + kelly
                  └────────────┬────────────┘
                               │ SizedOpportunity
                  ┌────────────▼────────────┐
                  │  execution.executor     │  ← asyncio.gather both legs
                  └────────────┬────────────┘
                               │
                  ┌────────────▼────────────┐
                  │   storage.db (SQLite)   │
                  └────────────┬────────────┘
                               │
                  ┌────────────▼────────────┐
                  │ dashboard/app.py        │  ← Streamlit, read-only
                  └─────────────────────────┘
```

---

## File tree

```
poly-arbitrage-bot/
├── src/
│   ├── clients/
│   │   ├── base.py                 # BaseExchangeClient ABC
│   │   ├── polymarket_client.py    # py-clob-client wrapper
│   │   └── kalshi_client.py        # RSA-PSS signed REST client
│   ├── matching/
│   │   ├── fuzzy.py                # rapidfuzz + entity overlap
│   │   └── market_matcher.py       # cross-exchange pair finder
│   ├── analysis/
│   │   ├── edge_calculator.py      # edge math (cross-ex + bundle)
│   │   ├── slippage_estimator.py   # walks orderbook depth
│   │   └── arbitrage_analyzer.py   # orchestrates detection
│   ├── execution/
│   │   ├── executor.py             # parallel leg placement
│   │   └── partial_fill_recovery.py
│   ├── risk/
│   │   ├── kelly.py                # quarter-Kelly sizing
│   │   ├── circuit_breaker.py      # 15% drawdown kill
│   │   └── position_limits.py      # per-market & global caps
│   ├── storage/
│   │   ├── db.py                   # SQLite connection + queries
│   │   └── schema.sql              # 4 tables
│   ├── config/
│   │   └── settings.py             # pydantic-settings BaseSettings
│   └── utils/
│       ├── retry.py                # tenacity wrappers
│       └── logger.py               # JSON-line stdlib logging
├── dashboard/
│   └── app.py                      # Streamlit
├── tests/
│   ├── test_arbitrage_math.py      # CarlosIbCu 3-case fixtures
│   ├── test_market_matcher.py
│   └── test_fee_calculator.py
├── scripts/
│   ├── paper_run.py
│   └── live_run.py
├── .env.example
├── .gitignore
├── LICENSE
├── pyproject.toml
├── README.md
├── REFACTOR_PLAN.md
└── DIFFERENCES_FROM_SOURCES.md
```

---

## Decisions: keep / rewrite / drop

### From ImMike/polymarket-arbitrage (primary)

| What | Decision | Why |
|---|---|---|
| Module split (`clients/`, `core/`, `dashboard/`) | **Keep idea, rename `core/` → `analysis/`+`execution/`+`risk/`** | Cleaner separation of read-only logic vs side-effects |
| `MarketMatcher` text similarity | **Rewrite using rapidfuzz** | difflib is slow + monolithic; rapidfuzz is C-backed and modern. Same algorithmic shape (token sort + entity overlap) |
| Hardcoded NFL/NBA roster dicts | **Drop** | Brittle, stale, narrow. Use generic entity extraction (capitalized tokens, dates, numbers) |
| Bundle arb math (`1 - Σ ask >= edge`) | **Keep, harden with fee model** | Correct shape, but their fees are wrong (see below) |
| Cross-platform 4-direction enumeration | **Keep** | Sound logic; just was never wired to executor |
| Risk manager + kill switch | **Rewrite cleaner** | Their `auto_unwind_on_breach: false` makes kill switch advisory; we wire it as hard gate |
| `data_mode: real \| simulation` | **Keep as `LIVE_TRADING_ENABLED` + paper executor** | Same effect, simpler flag |
| YAML config | **Drop, use .env** | Matches user's poly-trading-bot style; one source of truth |
| FastAPI dashboard | **Drop, use Streamlit** | User's preferred stack |
| In-memory state | **Drop, use SQLite** | Crash recovery + post-hoc analytics |
| Sequential `asyncio.Queue` execution | **Rewrite to `asyncio.gather`** | Cross-exchange MUST fire both legs in parallel or one leg leaks edge |
| Hand-rolled retry | **Replace with tenacity** | Stated user convention |
| Hardcoded 1% Kalshi fee | **Replace with exact `ceil(0.07 * c * p * (1-p))` formula** | The hardcoded approximation systematically lies near $0.50 |
| Polymarket auth (TODO/incomplete) | **Replace with py-clob-client EIP-712** | Stated user convention |
| Kalshi client (read-only, no auth) | **Replace with full RSA-PSS auth + place_order** | Required for live trading |

### From CarlosIbCu (secondary)

| What | Decision | Why |
|---|---|---|
| 3-case strike-vs-strike arb math | **Adopt as test fixtures** | Compact and correct for strike-based markets; canonical pytest cases |
| URL-slug brute-force market generation | **Drop** | Only works for one market type (BTC hourly); generalises poorly |
| FastAPI + Next.js stack | **Drop** | User's stack is Streamlit |

### From WSOL12 (secondary)

| What | Decision | Why |
|---|---|---|
| Everything | **Drop, near-duplicate of CarlosIbCu** | Confirmed via `diff -rq` |

---

## Risks (where money gets lost)

1. **Partial fill on first leg.** Polymarket fills the NO at $0.38, Kalshi YES order rejects → naked NO position with no hedge. Mitigation: `partial_fill_recovery.py` runs immediately after `asyncio.gather`; on detection, market-cancels the unfilled leg or attempts re-quote within slippage budget.
2. **Market mismatch.** Matcher pairs "Trump 2024 election" with "Trump approval Q1" — both have payoff conditions involving Trump but resolve on different events. Mitigation: similarity threshold 0.85 for auto-trade, 0.65–0.85 logged as `review_required` and **never auto-traded**.
3. **Stale orderbook.** Quote refreshed 800 ms ago; by execution time, ask climbed 3¢ → edge gone. Mitigation: per-opportunity TTL (default 1500 ms) + revalidation immediately before execute.
4. **Fee under-estimation.** Wrong Kalshi formula → false positives near $0.50. Mitigation: exact formula in `edge_calculator.py`, unit-tested at boundary prices.
5. **Resolution timing mismatch.** Same event resolves at slightly different times on each exchange → carry risk. Mitigation: out of MVP scope; flag in opportunity log so user can filter.
6. **Negative-risk markets on Polymarket.** Multi-outcome markets with neg-risk adapter price differently. py-clob-client handles via `neg_risk` flag; we surface it through `OrderArgs`.
7. **Kalshi tier-jump penalty.** If position size crosses contract tiers, fee step changes. Slippage estimator must size below tier or recompute fee per tier.
8. **Live mode accidental enable.** Mitigation: `LIVE_TRADING_ENABLED=true` env **AND** `--live` CLI flag both required; refuse to start otherwise.

---

## Stages

1. **Clients** — `BaseExchangeClient`, `polymarket_client`, `kalshi_client`. Round-trip: fetch markets, fetch orderbook, get balance.
2. **Matching** — `fuzzy.py` (similarity helpers) + `market_matcher.py` (pair stream). Output: `Iterator[MatchedPair]`.
3. **Analyzer** — `edge_calculator` + `slippage_estimator` + `arbitrage_analyzer`. Output: `Opportunity` objects with `expected_profit_usd`, `confidence`, `legs`.
4. **Executor** — paper-mode default (logs only). Live-mode fires `asyncio.gather([leg_a, leg_b])`. Recovery on partial.
5. **Risk** — `kelly` (¼-Kelly), `circuit_breaker` (15% drawdown), `position_limits` (per-market USD cap, global exposure cap).
6. **Dashboard** — Streamlit reads SQLite: opportunities feed, trade log, P&L curve, balance trend.
7. **Tests** — arb math (CarlosIbCu fixtures), matcher (positives + negatives), fee calculator (Kalshi tier boundaries).
8. **README** — quickstart, env vars, paper→live promotion checklist.

Each stage is self-contained: clients have no knowledge of analyzer, analyzer has no knowledge of executor, executor has no knowledge of risk gate (composition lives in `scripts/`).

---

## Live-trading promotion gate

To go live, **all** of:
- `LIVE_TRADING_ENABLED=true` in `.env`
- `--live` flag passed to `scripts/live_run.py`
- `scripts/live_run.py` boot-time check confirms balance < `MAX_POSITION_USD * 4` (sanity cap on accidental scale)
- Both Polymarket and Kalshi clients auth-check pass

Anything else → refuse to start with a clear error.
