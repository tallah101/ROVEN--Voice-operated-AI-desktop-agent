"""Fuzzy matching for spoken names of apps, windows and files."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_SUFFIX = re.compile(r"\.(exe|lnk|url)$", re.I)
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize(text: str) -> str:
    text = _SUFFIX.sub("", text.strip().lower()).replace("_", " ")
    return " ".join(_NON_WORD.sub(" ", text).split())


def match_score(query: str, candidate: str) -> float:
    q, c = normalize(query), normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q.replace(" ", "") == c.replace(" ", ""):
        return 0.95
    coverage = min(len(q), len(c)) / max(len(q), len(c))
    if f" {q} " in f" {c} ":
        return 0.7 + 0.3 * coverage        # whole-word match; shorter candidates win
    if q in c:
        return 0.55 + 0.3 * coverage
    return SequenceMatcher(None, q, c).ratio() * 0.75


def rank(query: str, candidates: list[str], min_score: float = 0.5, limit: int = 5) -> list[tuple[int, float]]:
    scored = [(i, match_score(query, c)) for i, c in enumerate(candidates)]
    scored = [s for s in scored if s[1] >= min_score]
    scored.sort(key=lambda s: s[1], reverse=True)
    return scored[:limit]
