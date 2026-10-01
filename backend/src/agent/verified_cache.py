"""Exact / near-exact match against certified golden_records (verified-answer cache)."""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import GoldenRecord

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_question(question: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = (question or "").strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def token_set(question: str) -> set[str]:
    norm = normalize_question(question)
    if not norm:
        return set()
    return {t for t in norm.split(" ") if t}


def token_overlap(a: str, b: str) -> float:
    """Jaccard overlap of normalized token sets. Empty → 0.0."""
    ta, tb = token_set(a), token_set(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return inter / union


async def find_verified_sql(
    session: AsyncSession,
    connection_id: str,
    question: str,
    *,
    min_overlap: float = 0.9,
) -> Optional[GoldenRecord]:
    """Return a golden record with exact normalized match or high token overlap.

    Prefers exact normalized equality; otherwise the highest overlap >= min_overlap.
    """
    q = (question or "").strip()
    if not q or not connection_id:
        return None

    result = await session.execute(
        select(GoldenRecord).where(GoldenRecord.connection_id == connection_id)
    )
    rows = list(result.scalars().all())
    if not rows:
        return None

    norm_q = normalize_question(q)
    best: GoldenRecord | None = None
    best_score = 0.0

    for row in rows:
        if not (row.sql or "").strip():
            continue
        norm_row = normalize_question(row.question or "")
        if norm_row and norm_row == norm_q:
            return row
        score = token_overlap(q, row.question or "")
        if score >= min_overlap and score > best_score:
            best = row
            best_score = score

    return best
