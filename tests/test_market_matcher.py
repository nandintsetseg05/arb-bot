"""Market matcher tests.

We care about three things:
  1. Strong positives (same event, different wording) → AUTO tier.
  2. Plausible-but-different events → REVIEW tier or below.
  3. Clearly unrelated events → discarded.
"""

from __future__ import annotations

import pytest

from src.clients.base import Market, Venue
from src.matching.fuzzy import similarity
from src.matching.market_matcher import MarketMatcher, MatchTier


def _poly(question: str, category: str | None = None, mid: str = "p1") -> Market:
    return Market(
        venue=Venue.POLYMARKET,
        market_id=mid,
        question=question,
        outcomes=("Yes", "No"),
        yes_token_id="yes",
        no_token_id="no",
        category=category,
    )


def _kalshi(question: str, category: str | None = None, ticker: str = "k1") -> Market:
    return Market(
        venue=Venue.KALSHI,
        market_id=ticker,
        question=question,
        outcomes=("Yes", "No"),
        category=category,
    )


# --- fuzzy primitive ---


def test_similarity_identical_strings_max() -> None:
    s = similarity("Will Trump win the 2024 election?", "Will Trump win the 2024 election?")
    assert s.text == pytest.approx(1.0)
    assert s.entity > 0.5


def test_similarity_paraphrase_high() -> None:
    s = similarity("Will Trump win the 2024 election?", "Trump to win 2024 presidential election")
    assert s.blended >= 0.65  # at minimum, REVIEW-tier candidate


def test_similarity_unrelated_low() -> None:
    s = similarity("Will Trump win the 2024 election?", "Will it rain in Seattle on Sunday?")
    assert s.blended < 0.4


def test_similarity_same_topic_different_payoff_distinguishable() -> None:
    """High text similarity but distinct entities → blend should still flag the difference."""
    s_same = similarity("Will Trump win the 2024 presidential election?", "Trump 2024 election win")
    s_diff = similarity("Will Trump win the 2024 election?", "Will Trump leave Twitter in 2024?")
    assert s_same.blended > s_diff.blended


# --- matcher ---


def test_matcher_promotes_strong_match_to_auto() -> None:
    poly = [_poly("Will Trump win the 2024 election?", category="politics")]
    kalshi = [_kalshi("Trump to win the 2024 presidential election", category="politics")]
    m = MarketMatcher(auto_threshold=0.65, review_threshold=0.45)
    pairs = m.match(poly, kalshi)
    assert len(pairs) == 1
    assert pairs[0].tier is MatchTier.AUTO


def test_matcher_keeps_weaker_match_in_review_tier() -> None:
    poly = [_poly("Will Trump be inaugurated in 2025?", category="politics")]
    kalshi = [_kalshi("Trump to win 2024 presidential election", category="politics")]
    m = MarketMatcher(auto_threshold=0.85, review_threshold=0.45)
    pairs = m.match(poly, kalshi)
    assert len(pairs) == 1
    assert pairs[0].tier is MatchTier.REVIEW


def test_matcher_discards_unrelated() -> None:
    poly = [_poly("Will Trump win the 2024 election?")]
    kalshi = [_kalshi("Will the Lakers win the NBA Finals?")]
    m = MarketMatcher(auto_threshold=0.85, review_threshold=0.45)
    pairs = m.match(poly, kalshi)
    assert pairs == []


def test_matcher_returns_best_kalshi_per_poly() -> None:
    poly = [_poly("Will Trump win the 2024 election?", category="politics")]
    kalshi = [
        _kalshi("Will Trump leave Twitter in 2024?", category="politics", ticker="t1"),
        _kalshi("Trump to win the 2024 presidential election", category="politics", ticker="t2"),
        _kalshi("Will Bitcoin hit $100k in 2024?", category="crypto", ticker="t3"),
    ]
    m = MarketMatcher(auto_threshold=0.6, review_threshold=0.3)
    pairs = m.match(poly, kalshi)
    assert len(pairs) == 1
    assert pairs[0].kalshi.market_id == "t2"


def test_matcher_threshold_validation() -> None:
    with pytest.raises(ValueError):
        MarketMatcher(auto_threshold=0.5, review_threshold=0.7)
