"""Kalshi REST client with RSA-PSS-SHA256 request signing.

Auth scheme (production trading):
  Headers:
    KALSHI-ACCESS-KEY:       <key id>
    KALSHI-ACCESS-TIMESTAMP: <unix epoch ms as string>
    KALSHI-ACCESS-SIGNATURE: base64(RSA_PSS_SHA256(timestamp + METHOD + path))
  where `path` is the request path including the `/trade-api/v2` prefix, no querystring.
"""

from __future__ import annotations

import base64
import logging
import math
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from src.clients.base import (
    BaseExchangeClient,
    Market,
    Orderbook,
    OrderbookLevel,
    OrderRequest,
    OrderResult,
    Outcome,
    Side,
    Venue,
)
from src.utils.retry import retry_api_call

logger = logging.getLogger(__name__)


def _load_rsa_private_key(path: Path) -> RSAPrivateKey:
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise RuntimeError(f"Kalshi private key at {path} is not RSA")
    return key


def kalshi_taker_fee_usd(contracts: int, price: float) -> float:
    """Exact Kalshi taker fee: ceil(0.07 * contracts * price * (1-price)) cents.

    Returned in USD. Fee is per-trade and applies on each fill.
    Reference: https://kalshi.com/docs/fees
    """
    if contracts <= 0 or not 0.0 < price < 1.0:
        return 0.0
    cents = math.ceil(7 * contracts * price * (1 - price))
    return cents / 100.0


class KalshiClient(BaseExchangeClient):
    venue = Venue.KALSHI

    def __init__(
        self,
        *,
        host: str,
        key_id: str,
        private_key_path: Path,
        timeout: float = 15.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.key_id = key_id
        self._private_key = _load_rsa_private_key(private_key_path)
        # path prefix that participates in signature, e.g. "/trade-api/v2"
        # `host` is a full URL; pull the prefix from it.
        url = httpx.URL(self.host)
        self._path_prefix = url.path.rstrip("/")  # e.g. "/trade-api/v2"
        self._client = httpx.AsyncClient(base_url=self.host, timeout=timeout)

    # ----- signing -----

    def _sign(self, method: str, path: str, timestamp_ms: str) -> str:
        message = f"{timestamp_ms}{method.upper()}{path}".encode()
        sig = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode("ascii")

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        full_path = f"{self._path_prefix}{path}" if not path.startswith(self._path_prefix) else path
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": self._sign(method, full_path, ts),
            "accept": "application/json",
            "content-type": "application/json",
        }

    @retry_api_call
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = self._auth_headers(method, path)
        r = await self._client.request(
            method, path, params=params, json=json_body, headers=headers
        )
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return {}
        data = r.json()
        if not isinstance(data, dict):
            return {"data": data}
        return data

    # ----- public surface -----

    async def list_markets(self, *, active_only: bool = True) -> list[Market]:
        params: dict[str, Any] = {"limit": 1000}
        if active_only:
            params["status"] = "open"
        out: list[Market] = []
        cursor: str | None = None
        for _ in range(20):  # safety cap
            if cursor:
                params["cursor"] = cursor
            resp = await self._request("GET", "/markets", params=params)
            for m in resp.get("markets", []):
                out.append(self._parse_market(m))
            cursor = resp.get("cursor") or None
            if not cursor:
                break
        return out

    @staticmethod
    def _parse_market(raw: dict[str, Any]) -> Market:
        ticker = str(raw.get("ticker") or "")
        title = str(raw.get("title") or raw.get("subtitle") or raw.get("yes_sub_title") or ticker)
        return Market(
            venue=Venue.KALSHI,
            market_id=ticker,
            question=title,
            outcomes=("Yes", "No"),
            closes_at_iso=raw.get("close_time"),
            category=raw.get("category"),
            raw=raw,
        )

    async def get_orderbook(self, market_id: str, outcome: Outcome) -> Orderbook:
        resp = await self._request("GET", f"/markets/{market_id}/orderbook")
        ob = resp.get("orderbook", {}) if isinstance(resp.get("orderbook"), dict) else resp
        # Kalshi returns YES book; for NO, we mirror.
        yes_levels = ob.get("yes") or []
        no_levels = ob.get("no") or []
        bids_yes = self._levels(yes_levels)
        bids_no = self._levels(no_levels)
        # In Kalshi's representation, orderbook.yes are bids on YES (desc by price),
        # asks on YES are derivable from no-bids: ask_yes_price = 100 - bid_no_price.
        asks_yes = tuple(
            OrderbookLevel(price=(100 - lvl.price) / 100.0, size=lvl.size) for lvl in bids_no
        )
        bids_yes_norm = tuple(
            OrderbookLevel(price=lvl.price / 100.0, size=lvl.size) for lvl in bids_yes
        )
        if outcome is Outcome.YES:
            return Orderbook(
                venue=Venue.KALSHI,
                market_id=market_id,
                outcome=Outcome.YES,
                bids=bids_yes_norm,
                asks=asks_yes,
                fetched_at_ms=int(time.time() * 1000),
            )
        # outcome NO: bids on NO are yes-asks-mirrored; asks on NO are yes-bids-mirrored.
        bids_no_norm = tuple(
            OrderbookLevel(price=lvl.price / 100.0, size=lvl.size) for lvl in bids_no
        )
        asks_no = tuple(
            OrderbookLevel(price=(100 - lvl.price) / 100.0, size=lvl.size) for lvl in bids_yes
        )
        return Orderbook(
            venue=Venue.KALSHI,
            market_id=market_id,
            outcome=Outcome.NO,
            bids=bids_no_norm,
            asks=asks_no,
            fetched_at_ms=int(time.time() * 1000),
        )

    @staticmethod
    def _levels(raw_levels: list[Any]) -> list[OrderbookLevel]:
        out: list[OrderbookLevel] = []
        for entry in raw_levels:
            if isinstance(entry, list) and len(entry) >= 2:
                out.append(OrderbookLevel(price=float(entry[0]), size=float(entry[1])))
            elif isinstance(entry, dict):
                out.append(
                    OrderbookLevel(price=float(entry.get("price", 0)), size=float(entry.get("size", 0)))
                )
        out.sort(key=lambda x: -x.price)
        return out

    async def get_balance_usd(self) -> float:
        resp = await self._request("GET", "/portfolio/balance")
        # Kalshi returns balance in cents.
        cents = resp.get("balance")
        if cents is None:
            return 0.0
        try:
            return float(cents) / 100.0
        except (TypeError, ValueError):
            return 0.0

    async def place_order(self, req: OrderRequest) -> OrderResult:
        if req.venue is not Venue.KALSHI:
            raise ValueError(f"KalshiClient cannot place {req.venue} order")
        side_str = "yes" if req.outcome is Outcome.YES else "no"
        action = "buy" if req.side is Side.BUY else "sell"
        # Kalshi prices: integer cents 1..99
        price_cents = max(1, min(99, round(req.price * 100)))
        body: dict[str, Any] = {
            "ticker": req.market_id,
            "action": action,
            "side": side_str,
            "count": int(req.size),
            "type": "limit",
            "yes_price" if side_str == "yes" else "no_price": price_cents,
            "client_order_id": req.client_id or f"poly-arb-{int(time.time() * 1000)}",
        }
        try:
            resp = await self._request("POST", "/portfolio/orders", json_body=body)
        except httpx.HTTPStatusError as exc:
            return OrderResult(
                venue=Venue.KALSHI,
                venue_order_id=None,
                accepted=False,
                filled_size=0.0,
                avg_fill_price=req.price,
                fee_usd=0.0,
                raw_response={"status": exc.response.status_code, "body": exc.response.text},
                error=f"http_{exc.response.status_code}",
            )
        order = resp.get("order", {}) if isinstance(resp.get("order"), dict) else resp
        order_id = order.get("order_id") or order.get("id")
        filled = float(order.get("filled_quantity") or 0)
        fee_usd = kalshi_taker_fee_usd(int(filled or req.size), req.price)
        return OrderResult(
            venue=Venue.KALSHI,
            venue_order_id=str(order_id) if order_id else None,
            accepted=True,
            filled_size=filled,
            avg_fill_price=req.price,
            fee_usd=fee_usd,
            raw_response=resp,
            error=None,
        )

    async def cancel_order(self, venue_order_id: str) -> bool:
        try:
            await self._request("DELETE", f"/portfolio/orders/{venue_order_id}")
            return True
        except Exception as exc:
            logger.warning("kalshi cancel failed", extra={"error": str(exc)})
            return False

    async def close(self) -> None:
        await self._client.aclose()
