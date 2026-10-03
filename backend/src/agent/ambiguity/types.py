"""Ambiguity dataclasses and shared token helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Letters/digits in any script. No English stopword list.
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)

_MAX_OPTIONS = 4
_MAX_LABEL_LEN = 80
_OTHER_OPTION = "Other — I'll rephrase the question"


@dataclass(frozen=True)
class AmbiguityDecision:
    should_clarify: bool
    reason: str
    options: list[str]


@dataclass(frozen=True)
class InterpretationCandidate:
    label: str
    question: str
    tables: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterpretationProposal:
    status: str  # clear | assumed | ambiguous | unanswerable
    assumption: str
    reason: str
    candidates: tuple[InterpretationCandidate, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    should_clarify: bool
    status: str  # clear | assumed | ambiguous | unanswerable | failed_open
    reason: str
    assumption: str
    options: list[str] = field(default_factory=list)
    decision_why: str = ""
    selected: InterpretationCandidate | None = None
    # When True, generator/gate should sample K SQLs and decide via execution.
    needs_execution_gate: bool = False
    # Intent-level decision points from the LLM (vague terms, missing formulas).
    decision_points: tuple[str, ...] = ()

def _tokens(text: str) -> list[str]:
    # Split snake_case identifiers so schema names match spoken words.
    parts: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        parts.extend(p for p in match.group(0).lower().split("_") if p)
    return parts


def _content_tokens(text: str) -> set[str]:
    return {t for t in _tokens(text) if len(t) > 1}
