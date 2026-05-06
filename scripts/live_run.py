"""Live-mode entry point. Multiple gates required to start.

Required to actually fire real orders:
  1. LIVE_TRADING_ENABLED=true in .env
  2. --live CLI flag
  3. Both auth checks pass
  4. Sum of balances <= MAX_POSITION_USD * 4 (sanity cap on accidental scale)

Anything missing → exit non-zero with a clear message.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.runner import build_clients, run_loop  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.execution.executor import ExecutionMode  # noqa: E402
from src.utils.logger import setup_logging  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="poly-arbitrage-bot live runner")
    p.add_argument("--live", action="store_true", help="Required to actually trade real funds.")
    return p.parse_args()


async def _preflight() -> None:
    settings = get_settings()

    if not settings.live_trading_enabled:
        print("[abort] LIVE_TRADING_ENABLED is false in .env. Refusing to start.", file=sys.stderr)
        sys.exit(2)

    settings.assert_polymarket_ready()
    settings.assert_kalshi_ready()

    clients = build_clients(settings)
    try:
        balances = []
        for venue, client in clients.items():
            bal = await client.get_balance_usd()
            balances.append((venue.value, bal))
            print(f"[preflight] {venue.value} balance: ${bal:,.2f}")
        total = sum(b for _, b in balances)
        ceiling = settings.max_position_usd * 4
        if total > ceiling:
            print(
                f"[abort] total balance ${total:,.2f} > sanity ceiling ${ceiling:,.2f}. "
                "Lower account funding or raise MAX_POSITION_USD intentionally.",
                file=sys.stderr,
            )
            sys.exit(3)
    finally:
        for c in clients.values():
            await c.close()


def main() -> None:
    args = _parse_args()
    setup_logging(get_settings().log_level)

    if not args.live:
        print(
            "[abort] live mode requires the --live CLI flag. Use scripts/paper_run.py for paper trading.",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(_preflight())
    asyncio.run(run_loop(mode=ExecutionMode.LIVE))


if __name__ == "__main__":
    main()
