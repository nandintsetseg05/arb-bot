"""Cross-exchange market pairing.

Two-tier output:
  - confidence >= AUTO_THRESHOLD  → MatchTier.AUTO        (eligible for auto-trade)
  - REVIEW_THRESHOLD <= conf < AUTO_THRESHOLD → MatchTier.REVIEW  (logged, never auto-traded)
  - below REVIEW_THRESHOLD → discarded
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from src.clients.base import Market, Venue
from src.matching.fuzzy import SimilarityBreakdown, similarity

logger = logging.getLogger(__name__)


class MatchTier(str, Enum):
    AUTO = "auto"
    REVIEW = "review"


@dataclass(frozen=True)
class MatchedPair:
    polymarket: Market
    kalshi: Market
    score: SimilarityBreakdown
    tier: MatchTier


class MarketMatcher:
    """N×M comparison with category prefilter for speed."""

    def __init__(self, *, auto_threshold: float = 0.85, review_threshold: float = 0.65) -> None:
        if not 0 <= review_threshold <= auto_threshold <= 1:
            raise ValueError("require 0 <= review <= auto <= 1")
        self.auto = auto_threshold
        self.review = review_threshold

    def match(
        self,
        polymarket_markets: list[Market],
        kalshi_markets: list[Market],
    ) -> list[MatchedPair]:
        out: list[MatchedPair] = []
        # Pre-bucket Kalshi by category to reduce O(N*M) work where possible.
        # Fall back to scanning all when category is missing.
        by_cat: dict[str | None, list[Market]] = {}
        for k in kalshi_markets:
            by_cat.setdefault(self._cat(k), []).append(k)
        all_kalshi: list[Market] = list(kalshi_markets)

        for p in polymarket_markets:
            if p.venue is not Venue.POLYMARKET:
                continue
            candidates = by_cat.get(self._cat(p)) or all_kalshi
            best: MatchedPair | None = None
            for k in candidates:
                if k.venue is not Venue.KALSHI:
                    continue
                score = similarity(p.question, k.question)
                if score.blended < self.review:
                    continue
                tier = MatchTier.AUTO if score.blended >= self.auto else MatchTier.REVIEW
                if best is None or score.blended > best.score.blended:
                    best = MatchedPair(polymarket=p, kalshi=k, score=score, tier=tier)
            if best is not None:
                out.append(best)
        logger.info(
            "matcher done",
            extra={"poly": len(polymarket_markets), "kalshi": len(kalshi_markets), "matches": len(out)},
        )
        return out

    @staticmethod
    def _cat(m: Market) -> str | None:
        if not m.category:
            return None
        return m.category.strip().lower() or None
