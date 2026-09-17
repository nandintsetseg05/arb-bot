"""Live-mode entry point — HARD-DISABLED in the crypto-research build.

Phase 0 of CRYPTO_REFACTOR_PLAN.md makes this system paper-only. This entry point
fails closed: it never builds clients, never checks balances, never places orders.
It exits non-zero with a clear message directing the operator to paper mode.

Re-enabling live trading is a deliberate, gated decision (see the plan's final Gate),
not a flag flip.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DISABLED_MESSAGE = (
    "[abort] Live trading is disabled in the crypto-research build.\n"
    "        This system is paper-only (CRYPTO_REFACTOR_PLAN.md Phase 0).\n"
    "        Run paper mode instead:  python scripts/paper_run.py"
)


def main() -> None:
    print(_DISABLED_MESSAGE, file=sys.stderr)
    sys.exit(4)


if __name__ == "__main__":
    main()
