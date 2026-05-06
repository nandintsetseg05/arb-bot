"""Text-similarity primitives used by the cross-exchange market matcher.

Uses rapidfuzz (C-backed) instead of difflib. Computes a blended score:
  blend = 0.65 * token_set_ratio + 0.35 * entity_overlap_jaccard

Entity overlap looks at capitalised tokens, 4-digit years, dollar amounts, and
explicit numbers — this rescues things like "Trump 2024" / "TRUMP-2024" and
catches false matches where text is similar but the named entities differ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, utils

_CAPS_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DOLLAR_RE = re.compile(r"\$[0-9][0-9,]*(?:\.\d+)?[kKmMbB]?")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "for", "to", "by", "and", "or",
    "will", "be", "is", "are", "was", "were", "vs", "vs.",
}


def normalize(text: str) -> str:
    s = text.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def extract_entities(text: str) -> set[str]:
    out: set[str] = set()
    out.update(m.group(0).lower() for m in _CAPS_RE.finditer(text))
    out.update(m.group(0) for m in _YEAR_RE.finditer(text))
    out.update(m.group(0).lower() for m in _DOLLAR_RE.finditer(text))
    out.update(m.group(0) for m in _NUMBER_RE.finditer(text))
    return {tok for tok in out if tok not in _STOPWORDS and len(tok) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


@dataclass(frozen=True)
class SimilarityBreakdown:
    text: float
    entity: float
    blended: float


def similarity(q1: str, q2: str) -> SimilarityBreakdown:
    norm1 = normalize(q1)
    norm2 = normalize(q2)
    text = fuzz.token_set_ratio(norm1, norm2, processor=utils.default_process) / 100.0
    e1 = extract_entities(q1)
    e2 = extract_entities(q2)
    entity = jaccard(e1, e2)
    blended = 0.65 * text + 0.35 * entity
    return SimilarityBreakdown(text=text, entity=entity, blended=blended)
