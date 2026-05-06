# poly-arbitrage-bot

[![tests](https://github.com/zostaff/poly-arbitrage-bot/actions/workflows/test.yml/badge.svg)](https://github.com/zostaff/poly-arbitrage-bot/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![status](https://img.shields.io/badge/status-alpha-orange)](#status)

> **Status: alpha. Paper mode only is recommended.** Live trading exists but is gated behind an env flag, an explicit CLI flag, and a balance sanity cap. The author runs this in paper mode and accepts no responsibility for live-mode losses. Read [SECURITY.md](SECURITY.md) before running.

Arbitrage bot for prediction markets. Two strategies:

1. **Cross-exchange** between Polymarket and Kalshi when the same event is mispriced.
   Example: `Trump 2024` at $0.62 on Polymarket and $0.59 on Kalshi → buy `NO Polymarket @ 0.38` + `YES Kalshi @ 0.59`. Total cost $0.97. One leg pays $1 at resolution. $0.03 minus fees minus slippage.
2. **Intra-Polymarket bundle** on multi-outcome markets where `Σ ask < $1` (or `Σ bid > $1` for the short side).

Built standalone — no shared modules with my other bots.

---

## Quick start (paper mode)

```bash
git clone https://github.com/zostaff/poly-arbitrage-bot
cd poly-arbitrage-bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# fill POLYMARKET_PK, KALSHI_KEY_ID, KALSHI_PRIVATE_KEY_PATH

pytest
python scripts/paper_run.py
```

In another terminal:

```bash
streamlit run dashboard/app.py
```

The paper run uses **real prices from both exchanges** but logs simulated fills to SQLite. No funds at risk.

---

## Going live

Live mode requires:

1. `LIVE_TRADING_ENABLED=true` in `.env`
2. `--live` flag on the CLI: `python scripts/live_run.py --live`
3. Both auth checks pass at boot
4. Account balance ≤ `MAX_POSITION_USD * 4` (sanity cap)

Refusing any of the above → bot exits with a clear error.

---

## Stack

- Python 3.11+ (3.12 recommended)
- [`py-clob-client`](https://github.com/Polymarket/py-clob-client) — Polymarket CLOB with EIP-712 order signing
- `cryptography` — Kalshi RSA-PSS auth
- `httpx` async — Kalshi REST
- `tenacity` — retry policy on every external call
- `rapidfuzz` — market matching
- `pydantic` + `pydantic-settings` — typed config from `.env`
- `sqlite3` (stdlib) — telemetry, opportunities, trade log
- `streamlit` — dashboard

---

## Layout

```
src/clients/        Polymarket + Kalshi exchange clients
src/matching/       Cross-exchange market pairing
src/analysis/       Edge calculation, slippage estimation
src/execution/      Parallel leg placement + partial-fill recovery
src/risk/           Quarter-Kelly, circuit breaker, position limits
src/storage/        SQLite schema + queries
src/config/         Settings (.env via pydantic)
src/utils/          Retry decorators, JSON-line logger
dashboard/          Streamlit (read-only over SQLite)
scripts/            Paper + live entry points
tests/              Arbitrage math, matcher, fee calculator
```

Architecture detail in [REFACTOR_PLAN.md](REFACTOR_PLAN.md). Provenance and what was rewritten from source repos in [DIFFERENCES_FROM_SOURCES.md](DIFFERENCES_FROM_SOURCES.md).

---

## Configuration

All in `.env`. Copy `.env.example`. The important knobs:

| Var | Default | Purpose |
|---|---|---|
| `LIVE_TRADING_ENABLED` | `false` | Master switch. Live mode also requires `--live` CLI flag. |
| `MIN_EDGE_BPS` | `50` | Minimum net edge after fees + slippage. |
| `MAX_POSITION_USD` | `500` | Hard cap per opportunity. |
| `QUARTER_KELLY` | `true` | ¼-Kelly sizing recommended. |
| `DRAWDOWN_LIMIT` | `0.15` | Circuit breaker trip from peak equity. |
| `MATCH_AUTO_THRESHOLD` | `0.85` | Min similarity for cross-exchange auto-trade. |
| `MATCH_REVIEW_THRESHOLD` | `0.65` | Pairs in `[0.65, 0.85)` are logged but never auto-traded. |
| `OPPORTUNITY_TTL_MS` | `1500` | Stale opportunities are dropped. |

---

## Tests

```bash
pytest -v
```

The arbitrage math suite includes the canonical 3-case strike comparison from prediction-market arbitrage literature (Polymarket strike vs Kalshi strike, all three orderings). The fee calculator tests verify Kalshi's exact `ceil(0.07 * c * p * (1-p))` formula at boundary prices.

---

## Contributing

Issues and PRs welcome. See [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) for issue templates and [`CHANGELOG.md`](CHANGELOG.md) for release history. Security issues: please follow [SECURITY.md](SECURITY.md) and **do not** open a public issue for vulnerabilities.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Disclaimer

This is research software for prediction-market arbitrage. **It is not financial advice. It comes with no warranty.**

Prediction markets carry real risk including but not limited to: total loss of deposited capital, resolution disputes, exchange-side bugs, regulatory action, network outages, partial fills, fee miscalculations, and model error. The author runs this bot in paper mode only and **makes no guarantee of profit** under any conditions.

If you choose to run this bot in live mode against real funds, that decision is yours alone. The author accepts **no liability** for losses, missed opportunities, regulatory consequences, or any other harm arising from use of this software.

Read [REFACTOR_PLAN.md](REFACTOR_PLAN.md) "Risks" section and [SECURITY.md](SECURITY.md) before going live.
