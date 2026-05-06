# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Live-mode reconciliation worker (compute realised P&L from settled trades).
- Mark-to-market positions in `CircuitBreaker` (currently uses cash balance only).
- Async semaphore for proactive rate limiting (currently retry-on-429 only).
- Integration tests with recorded API fixtures.

## [0.1.0] - 2026-05-06

### Added
- Initial scaffold: clients, matching, analysis, execution, risk, storage, dashboard.
- Polymarket client via `py-clob-client` (EIP-712 order signing).
- Kalshi client with RSA-PSS-SHA256 request signing (demo + prod endpoints).
- `rapidfuzz`-based market matcher with two-tier confidence (auto / review).
- Cross-exchange arbitrage detector (4-direction enumeration with depth walking).
- Intra-Polymarket bundle arbitrage detector (long: Σ ask < 1, short: Σ bid > 1).
- Exact Kalshi taker-fee formula `ceil(0.07 * c * p * (1-p))` cents.
- Quarter-Kelly sizing with hard position caps.
- 15% drawdown circuit breaker.
- SQLite telemetry (opportunities, trades, legs, balance snapshots).
- Streamlit dashboard (read-only).
- Paper-mode default; live-mode gated behind env flag, CLI flag, and balance sanity cap.
- 37 unit tests (arbitrage math, fee boundaries, matcher behaviour).

[Unreleased]: https://github.com/zostaff/poly-arbitrage-bot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zostaff/poly-arbitrage-bot/releases/tag/v0.1.0
