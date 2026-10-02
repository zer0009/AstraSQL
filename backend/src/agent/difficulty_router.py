"""Complexity-aware routing helpers for cheap vs escalated SQL generation.

Training-free heuristics (DecoSearch-style): keep a direct path for simple
questions and escalate only when structural signals or a prior failure appear.
"""

from __future__ import annotations

import re
from typing import Any, Literal

Difficulty = Literal["simple", "moderate", "challenging"]

_MULTI_SIGNAL = re.compile(
    r"\b(join|compare|versus|vs\.?|each|per\s+\w+|group|rank|top\s+\d+|"
    r"between|ratio|percentage|percent|year.over.year|trend)\b",
    re.IGNORECASE,
)
_NESTED_SIGNAL = re.compile(
    r"\b(who\s+also|that\s+have\s+never|without\s+any|not\s+in|"
    r"more\s+than\s+those|same\s+as)\b",
    re.IGNORECASE,
)


def estimate_difficulty(
    question: str,
    *,
    table_count: int = 0,
    prior_failure: bool = False,
) -> Difficulty:
    """Heuristic difficulty for routing (not a trained classifier)."""
    if prior_failure:
        return "challenging"
    q = (question or "").strip()
    if not q:
        return "simple"
    score = 0
    if len(q.split()) >= 18:
        score += 1
    if _MULTI_SIGNAL.search(q):
        score += 1
    if _NESTED_SIGNAL.search(q):
        score += 2
    if table_count >= 8:
        score += 1
    if table_count >= 40:
        score += 1
    if score >= 3:
        return "challenging"
    if score >= 1:
        return "moderate"
    return "simple"


def route_generation_plan(
    question: str,
    *,
    table_count: int = 0,
    prior_failure: bool = False,
    merge_interpret_generate: bool = False,
) -> dict[str, Any]:
    """Return a generation plan: direct vs escalate.

    - simple: single generate call (prefer merge when enabled)
    - moderate: normal pipeline
    - challenging: escalate (higher candidate count / keep resolver)
    """
    level = estimate_difficulty(
        question, table_count=table_count, prior_failure=prior_failure
    )
    if level == "simple":
        return {
            "difficulty": level,
            "path": "direct",
            "use_merge": True if merge_interpret_generate else merge_interpret_generate,
            "candidate_count": 1,
            "escalate_on_failure": True,
        }
    if level == "moderate":
        return {
            "difficulty": level,
            "path": "standard",
            "use_merge": merge_interpret_generate,
            "candidate_count": 1,
            "escalate_on_failure": True,
        }
    return {
        "difficulty": level,
        "path": "escalate",
        "use_merge": False,
        "candidate_count": 2,
        "escalate_on_failure": False,
    }
