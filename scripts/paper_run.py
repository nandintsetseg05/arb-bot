"""Paper-mode entry point. Real prices, simulated fills, SQLite log only."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.runner import run_loop  # noqa: E402
from src.execution.executor import ExecutionMode  # noqa: E402


def main() -> None:
    asyncio.run(run_loop(mode=ExecutionMode.PAPER))


if __name__ == "__main__":
    main()
