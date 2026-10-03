"""Deterministic trust labels. No LLM, no IO."""

from __future__ import annotations

from typing import Literal

import sqlglot
from sqlglot.errors import ParseError

TrustLevel = Literal["certified", "taught", "guessed", "clarifying", "failed"]

_CLARIFY_INTENT = "CLARIFICATION_NEEDED"


def normalize_sql(sql: str, dialect: str) -> str:
    """Canonicalize SQL for equality checks. Empty/unparseable input stays stripped."""
    text = (sql or "").strip()
    if not text:
        return ""
    try:
        tree = sqlglot.parse_one(text, dialect=dialect)
    except ParseError:
        return " ".join(text.lower().split())
    except Exception:
        return " ".join(text.lower().split())
    return tree.sql(dialect=dialect, pretty=False)


def compute_trust_level(
    *,
    intent: str,
    error: str | None,
    generated_sql: str,
    golden_sqls: list[str],
    used_golden: bool,
    dialect: str,
) -> TrustLevel:
    """Label how much of the project's language this answer used.

    - clarifying: no SQL and intent is CLARIFICATION_NEEDED
    - failed: error present and no generated SQL
    - certified: generated SQL matches a retrieved golden after normalize
    - taught: a golden was retrieved but SQL differs
    - guessed: no golden was used
    """
    sql = (generated_sql or "").strip()
    intent_norm = (intent or "").strip().upper()

    if not sql and intent_norm == _CLARIFY_INTENT:
        return "clarifying"
    if error and not sql:
        return "failed"
    if not sql:
        if intent_norm == _CLARIFY_INTENT:
            return "clarifying"
        return "failed"

    generated_norm = normalize_sql(sql, dialect)
    for golden in golden_sqls:
        if generated_norm and generated_norm == normalize_sql(golden, dialect):
            return "certified"

    if used_golden:
        return "taught"
    return "guessed"
