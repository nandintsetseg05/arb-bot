"""Crypto-only scan loop (paper research). Driven by the reviewed contract-pair registry.

Replaces the old title-matcher + cross/bundle analyzer path. For each eligible registered
pair it runs the intra-venue locked scan and the validator-gated cross-venue scan, and logs
every labelled result. No orders are placed — live execution is disabled (Phase 0), and paper
fill simulation + audit persistence arrive in Phase 6.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.analysis.crypto_scan import ScanRecord, scan_all  # noqa: E402
from src.clients.base import BaseExchangeClient, Venue  # noqa: E402
from src.clients.kalshi_client import KalshiClient  # noqa: E402
from src.clients.polymarket_client import PolymarketClient  # noqa: E402
from src.config.settings import Settings, get_settings  # noqa: E402
from src.execution.executor import ExecutionMode  # noqa: E402
from src.registry.pair_registry import ContractPair, eligible_pairs  # noqa: E402
from src.risk.circuit_breaker import CircuitBreaker  # noqa: E402
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
    clients: dict[Venue, BaseExchangeClient],
    pairs: list[ContractPair],
    settings: Settings,
) -> list[ScanRecord]:
    """One scan cycle over all eligible pairs; logs every labelled result."""
    records = await scan_all(
        clients,
        pairs,
        poly_fee_bps=settings.polymarket_taker_fee_bps,
        max_notional_usd=settings.max_position_usd,
    )
    for rec in records:
        r = rec.result
        logger.info(
            "scan",
            extra={
                "pair": rec.pair_id,
                "strategy": rec.strategy,
                "label": r.label,
                "net_usd": str(r.net_edge_usd),
                "contracts": r.contracts,
                "reason": r.reason,
                "mismatches": list(r.mismatches),
            },
        )
    return records


async def run_loop(*, mode: ExecutionMode) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "starting crypto scan",
        extra={"mode": mode.value, "kalshi_env": settings.kalshi_env.value},
    )

    db = Database(settings.db_full_path)
    breaker = CircuitBreaker(drawdown_limit=settings.drawdown_limit)
    clients = build_clients(settings)
    pairs = eligible_pairs(settings.registry_full_path)
    if not pairs:
        logger.warning(
            "no eligible pairs — approve+verify pairs in the registry to scan",
            extra={"registry": str(settings.registry_full_path)},
        )

    try:
        while True:
            t0 = time.time()
            try:
                await snapshot_balances(clients, db, breaker)
                records = await scan_once(clients, pairs, settings)
                logger.info(
                    "scan cycle complete",
                    extra={"records": len(records), "elapsed_s": time.time() - t0},
                )
            except Exception:
                logger.exception("scan cycle failed")
            await asyncio.sleep(settings.scan_interval_seconds)
    finally:
        for c in clients.values():
            await c.close()
        db.close()
