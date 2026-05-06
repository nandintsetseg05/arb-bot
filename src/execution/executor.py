"""Trade executor: paper-mode by default, live-mode behind explicit flag.

In paper mode, the analyzer's opportunity is logged to SQLite as a "filled" trade
at the quoted prices — useful for measuring strategy P&L on real prices without
risking funds.

In live mode, both legs of a cross-exchange opportunity fire via asyncio.gather.
After gather, partial-fill recovery kicks in: if exactly one leg succeeded, we
attempt to cancel the other (if pending) or unwind by selling the filled side.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from src.analysis.arbitrage_analyzer import Opportunity
from src.clients.base import (
    BaseExchangeClient,
    OrderRequest,
    OrderResult,
    Venue,
)
from src.execution.partial_fill_recovery import attempt_recovery
from src.risk.circuit_breaker import CircuitBreaker
from src.risk.position_limits import PositionLimits
from src.storage.db import Database

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class ExecutionDecision:
    accepted: bool
    reason: str
    opportunity_id: int | None = None
    trade_id: int | None = None


class Executor:
    def __init__(
        self,
        *,
        clients: Mapping[Venue, BaseExchangeClient],
        db: Database,
        breaker: CircuitBreaker,
        limits: PositionLimits,
        mode: ExecutionMode,
        opportunity_ttl_ms: int,
    ) -> None:
        self.clients = clients
        self.db = db
        self.breaker = breaker
        self.limits = limits
        self.mode = mode
        self.ttl_ms = opportunity_ttl_ms

    async def handle(self, opp: Opportunity) -> ExecutionDecision:
        # 1. Persist opportunity record (decision = traded/skipped/etc) regardless of action.
        opp_id = self._persist_opportunity(opp, decision="pending")

        # 2. Pre-flight gates.
        if opp.is_stale(self.ttl_ms):
            self._update_decision(opp_id, "skipped_stale", "ttl exceeded")
            return ExecutionDecision(False, "stale", opp_id)

        if opp.review_required:
            self._update_decision(opp_id, "review_required", "match below auto threshold")
            return ExecutionDecision(False, "review_required", opp_id)

        if self.breaker.is_tripped:
            self._update_decision(opp_id, "skipped_risk", f"breaker tripped: {self.breaker.trip_reason}")
            return ExecutionDecision(False, "circuit_breaker", opp_id)

        # Per-leg position-limit check on the dominant market_id.
        market_key = self._market_key(opp)
        decision = self.limits.check(market_key=market_key, requested_usd=opp.notional_usd)
        if not decision.allowed:
            self._update_decision(opp_id, "skipped_risk", decision.reason or "limit")
            return ExecutionDecision(False, "position_limit", opp_id)

        # 3. Reserve and execute.
        self.limits.reserve(market_key=market_key, amount_usd=opp.notional_usd)
        try:
            trade_id = self.db.insert_trade(opp_id, mode=self.mode.value)
            if self.mode is ExecutionMode.PAPER:
                await self._execute_paper(opp, trade_id)
                self._update_decision(opp_id, "traded", "paper")
                return ExecutionDecision(True, "paper_filled", opp_id, trade_id)

            await self._execute_live(opp, trade_id)
            self._update_decision(opp_id, "traded", "live")
            return ExecutionDecision(True, "live_filled", opp_id, trade_id)
        finally:
            self.limits.release(market_key=market_key, amount_usd=opp.notional_usd)

    # ------------------------------------------------------------------

    async def _execute_paper(self, opp: Opportunity, trade_id: int) -> None:
        """Simulate fills at the quoted prices; log to DB."""
        for leg in opp.legs:
            self.db.insert_leg(
                trade_id=trade_id,
                venue=leg.venue.value,
                market_id=leg.market_id,
                side=f"{leg.side.value}_{leg.outcome.value}",
                requested_size=leg.size,
                requested_price=leg.price,
                filled_size=leg.size,
                avg_fill_price=leg.price,
                fee_usd=0.0,  # paper: fees included in opp.fees_usd
                venue_order_id=f"PAPER-{int(time.time()*1000)}-{leg.venue.value}",
                status="paper_filled",
            )
        self.db.update_trade(
            trade_id,
            finished_at=_iso_now(),
            status="filled",
            realized_pnl=opp.net_edge_usd,
            notes="paper",
        )

    async def _execute_live(self, opp: Opportunity, trade_id: int) -> None:
        """Fire both legs concurrently; reconcile partial fills."""
        if len(opp.legs) != 2:
            # Bundle live execution: fire all in parallel, no recovery (prices are atomic on Polymarket).
            tasks = [self._submit(leg, trade_id) for leg in opp.legs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._reconcile_bundle(opp, trade_id, results)
            return

        leg_a, leg_b = opp.legs
        task_a = asyncio.create_task(self._submit(leg_a, trade_id))
        task_b = asyncio.create_task(self._submit(leg_b, trade_id))
        result_a, result_b = await asyncio.gather(task_a, task_b, return_exceptions=True)

        leg_results = {
            leg_a: result_a if not isinstance(result_a, BaseException) else None,
            leg_b: result_b if not isinstance(result_b, BaseException) else None,
        }
        if any(isinstance(r, BaseException) for r in (result_a, result_b)):
            for r in (result_a, result_b):
                if isinstance(r, BaseException):
                    logger.error("leg submission raised", extra={"err": str(r)})

        # Recovery: if one leg filled and the other didn't, attempt to neutralize.
        await attempt_recovery(
            clients=self.clients,
            db=self.db,
            trade_id=trade_id,
            leg_results=leg_results,
        )
        self.db.update_trade(
            trade_id,
            finished_at=_iso_now(),
            status="filled" if all(leg_results.values()) else "partial",
            realized_pnl=None,  # set by reconciliation job; mark None for now
            notes="live",
        )

    def _reconcile_bundle(self, opp: Opportunity, trade_id: int, results: list[object]) -> None:
        all_ok = all(isinstance(r, OrderResult) and r.accepted for r in results)
        self.db.update_trade(
            trade_id,
            finished_at=_iso_now(),
            status="filled" if all_ok else "partial",
            realized_pnl=opp.net_edge_usd if all_ok else None,
            notes="bundle",
        )

    async def _submit(self, leg: object, trade_id: int) -> OrderResult:
        # leg has fields venue, market_id, outcome, side, price, size
        from src.analysis.arbitrage_analyzer import OpportunityLeg

        assert isinstance(leg, OpportunityLeg)
        client = self.clients[leg.venue]
        leg_id = self.db.insert_leg(
            trade_id=trade_id,
            venue=leg.venue.value,
            market_id=leg.market_id,
            side=f"{leg.side.value}_{leg.outcome.value}",
            requested_size=leg.size,
            requested_price=leg.price,
            status="submitted",
        )
        req = OrderRequest(
            venue=leg.venue,
            market_id=leg.market_id,
            outcome=leg.outcome,
            side=leg.side,
            size=leg.size,
            price=leg.price,
            client_id=f"trade-{trade_id}-{leg.venue.value}",
        )
        try:
            result = await client.place_order(req)
        except Exception as exc:
            logger.exception("place_order failed", extra={"venue": leg.venue.value})
            self.db.update_leg(leg_id, status="error", settled_at=_iso_now())
            raise

        self.db.update_leg(
            leg_id,
            venue_order_id=result.venue_order_id,
            filled_size=result.filled_size,
            avg_fill_price=result.avg_fill_price,
            fee_usd=result.fee_usd,
            status="filled" if result.accepted else "rejected",
            settled_at=_iso_now(),
        )
        return result

    # ------------------------------------------------------------------

    def _persist_opportunity(self, opp: Opportunity, *, decision: str) -> int:
        leg_a = opp.legs[0]
        leg_b = opp.legs[1] if len(opp.legs) > 1 else None
        return self.db.insert_opportunity(
            arb_type=opp.arb_type.value,
            poly_market_id=opp.poly_market.market_id if opp.poly_market else None,
            poly_question=opp.poly_market.question if opp.poly_market else None,
            kalshi_ticker=opp.kalshi_market.market_id if opp.kalshi_market else None,
            kalshi_question=opp.kalshi_market.question if opp.kalshi_market else None,
            similarity=opp.confidence if opp.kalshi_market else None,
            leg_a_side=f"{leg_a.side.value}_{leg_a.outcome.value}",
            leg_a_price=leg_a.price,
            leg_a_venue=leg_a.venue.value,
            leg_b_side=f"{leg_b.side.value}_{leg_b.outcome.value}" if leg_b else None,
            leg_b_price=leg_b.price if leg_b else None,
            leg_b_venue=leg_b.venue.value if leg_b else None,
            gross_edge_usd=opp.gross_edge_usd,
            fees_usd=opp.fees_usd,
            slippage_usd=opp.slippage_buffer_usd,
            net_edge_usd=opp.net_edge_usd,
            edge_bps=opp.edge_bps,
            sized_usd=opp.notional_usd,
            decision=decision,
            decision_reason=None,
        )

    def _update_decision(self, opp_id: int, decision: str, reason: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE opportunities SET decision = ?, decision_reason = ? WHERE id = ?",
                (decision, reason, opp_id),
            )

    @staticmethod
    def _market_key(opp: Opportunity) -> str:
        if opp.poly_market and opp.kalshi_market:
            return f"x:{opp.poly_market.market_id}::{opp.kalshi_market.market_id}"
        if opp.poly_market:
            return f"p:{opp.poly_market.market_id}"
        return "unknown"


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
