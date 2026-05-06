"""Shared scan-loop logic used by both paper_run.py and live_run.py."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.analysis.arbitrage_analyzer import ArbitrageAnalyzer  # noqa: E402
from src.clients.base import BaseExchangeClient, Outcome, Venue  # noqa: E402
from src.clients.kalshi_client import KalshiClient  # noqa: E402
from src.clients.polymarket_client import PolymarketClient  # noqa: E402
from src.config.settings import Settings, get_settings  # noqa: E402
from src.execution.executor import ExecutionMode, Executor  # noqa: E402
from src.matching.market_matcher import MarketMatcher  # noqa: E402
from src.risk.circuit_breaker import CircuitBreaker  # noqa: E402
from src.risk.position_limits import PositionLimits  # noqa: E402
from src.storage.db import Database  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger("scripts.runner")


def build_clients(settings: Settings) -> dict[Venue, BaseExchangeClient]:
    settings.assert_polymarket_ready()
    settings.assert_kalshi_ready()
    poly = PolymarketClient(
        private_key=settings.polymarket_pk,
        host=settings.polymarket_host,
        chain_id=settings.polymarket_chain_id,
        signature_type=settings.polymarket_signature_type,
        funder=settings.polymarket_funder or None,
    )
    private_key_path = settings.kalshi_private_key_full_path
    assert private_key_path is not None  # asserted above
    kalshi = KalshiClient(
        host=settings.kalshi_host,
        key_id=settings.kalshi_key_id,
        private_key_path=private_key_path,
    )
    return {Venue.POLYMARKET: poly, Venue.KALSHI: kalshi}


async def snapshot_balances(
    clients: dict[Venue, BaseExchangeClient], db: Database, breaker: CircuitBreaker
) -> None:
    total = 0.0
    for venue, client in clients.items():
        try:
            bal = await client.get_balance_usd()
            db.snapshot_balance(venue.value, bal)
            total += bal
        except Exception as exc:
            logger.warning(
                "balance snapshot failed", extra={"venue": venue.value, "err": str(exc)}
            )
    breaker.update_equity(total)


async def scan_once(
    *,
    clients: dict[Venue, BaseExchangeClient],
    matcher: MarketMatcher,
    analyzer: ArbitrageAnalyzer,
    executor: Executor,
) -> int:
    """One scan cycle. Returns number of opportunities handled."""
    poly_client = clients[Venue.POLYMARKET]
    kalshi_client = clients[Venue.KALSHI]

    poly_markets, kalshi_markets = await asyncio.gather(
        poly_client.list_markets(active_only=True),
        kalshi_client.list_markets(active_only=True),
    )
    matches = matcher.match(poly_markets, kalshi_markets)
    handled = 0

    for pair in matches:
        if not pair.polymarket.yes_token_id or not pair.polymarket.no_token_id:
            continue
        try:
            ob_poly_yes, ob_poly_no, ob_k_yes, ob_k_no = await asyncio.gather(
                poly_client.get_orderbook(pair.polymarket.yes_token_id, Outcome.YES),
                poly_client.get_orderbook(pair.polymarket.no_token_id, Outcome.NO),
                kalshi_client.get_orderbook(pair.kalshi.market_id, Outcome.YES),
                kalshi_client.get_orderbook(pair.kalshi.market_id, Outcome.NO),
            )
        except Exception as exc:
            logger.warning(
                "orderbook fetch failed",
                extra={
                    "poly": pair.polymarket.market_id,
                    "kalshi": pair.kalshi.market_id,
                    "err": str(exc),
                },
            )
            continue
        opp = analyzer.detect_cross_exchange(
            pair,
            ob_poly_yes=ob_poly_yes,
            ob_poly_no=ob_poly_no,
            ob_kalshi_yes=ob_k_yes,
            ob_kalshi_no=ob_k_no,
        )
        if opp is not None:
            decision = await executor.handle(opp)
            handled += 1
            logger.info(
                "opportunity",
                extra={
                    "type": opp.arb_type.value,
                    "edge_bps": opp.edge_bps,
                    "net": opp.net_edge_usd,
                    "decision": decision.reason,
                    "review_required": opp.review_required,
                },
            )

    # Bundle scan: any Polymarket market with 3+ outcomes is a candidate; for MVP
    # we restrict to multi-outcome markets we already saw.
    for m in poly_markets:
        token_ids: list[str] = []
        if m.yes_token_id:
            token_ids.append(m.yes_token_id)
        if m.no_token_id:
            token_ids.append(m.no_token_id)
        if len(token_ids) < 2 or len(m.outcomes) < 3:
            continue
        try:
            books = await asyncio.gather(
                *(
                    poly_client.get_orderbook(tid, Outcome.YES if i == 0 else Outcome.NO)
                    for i, tid in enumerate(token_ids)
                )
            )
        except Exception:
            continue
        opp_long = analyzer.detect_bundle_long(m, books)
        if opp_long is not None:
            await executor.handle(opp_long)
            handled += 1
        opp_short = analyzer.detect_bundle_short(m, books)
        if opp_short is not None:
            await executor.handle(opp_short)
            handled += 1
    return handled


async def run_loop(*, mode: ExecutionMode) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("starting", extra={"mode": mode.value, "kalshi_env": settings.kalshi_env.value})

    db = Database(settings.db_full_path)
    breaker = CircuitBreaker(drawdown_limit=settings.drawdown_limit)
    limits = PositionLimits(
        max_per_market_usd=settings.max_position_usd,
        max_global_usd=settings.max_position_usd * 8,
    )
    clients = build_clients(settings)
    matcher = MarketMatcher(
        auto_threshold=settings.match_auto_threshold,
        review_threshold=settings.match_review_threshold,
    )
    analyzer = ArbitrageAnalyzer(
        min_edge_bps=settings.min_edge_bps,
        max_position_usd=settings.max_position_usd,
    )
    executor = Executor(
        clients=clients,
        db=db,
        breaker=breaker,
        limits=limits,
        mode=mode,
        opportunity_ttl_ms=settings.opportunity_ttl_ms,
    )

    try:
        while True:
            t0 = time.time()
            try:
                await snapshot_balances(clients, db, breaker)
                count = await scan_once(
                    clients=clients,
                    matcher=matcher,
                    analyzer=analyzer,
                    executor=executor,
                )
                logger.info(
                    "scan cycle complete",
                    extra={"handled": count, "elapsed_s": time.time() - t0},
                )
            except Exception:
                logger.exception("scan cycle failed")
            await asyncio.sleep(settings.scan_interval_seconds)
    finally:
        for c in clients.values():
            await c.close()
        db.close()
