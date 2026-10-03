"""Per-connection SQL conventions (join type, sort direction, etc.).

Conventions are stored in the semantic layer via ``record_learned_convention``.
No English business word lists — only structural SQL preferences.
"""

from __future__ import annotations

import re
from typing import Any

from src.context.learning_loop import record_learned_convention

_JOIN_RE = re.compile(
    r"\b(left|inner|right|full)\s+join\b", re.IGNORECASE
)


def detect_join_type(sql: str) -> str | None:
    m = _JOIN_RE.search(sql or "")
    if not m:
        if re.search(r"\bjoin\b", sql or "", re.IGNORECASE):
            return "inner"  # bare JOIN ≡ INNER in SQL
        return None
    return m.group(1).lower()


def join_type_convention_text(join_type: str) -> str:
    jt = (join_type or "inner").lower()
    return (
        f"Default multi-table join type for this connection is {jt.upper()} JOIN "
        f"unless the question explicitly requires otherwise."
    )


def record_join_type_convention(
    semantic_layer_dict: dict[str, Any],
    chosen_sql: str,
) -> dict[str, Any]:
    """Record the join type from a user-accepted SQL as a connection convention."""
    jt = detect_join_type(chosen_sql)
    if not jt:
        return semantic_layer_dict
    return record_learned_convention(
        semantic_layer_dict, join_type_convention_text(jt)
    )


def record_direction_convention(
    semantic_layer_dict: dict[str, Any],
    *,
    metric_hint: str,
    direction: str,
) -> dict[str, Any]:
    """Record MIN vs MAX / ASC vs DESC style convention from feedback."""
    metric = (metric_hint or "metric").strip()
    d = (direction or "").strip().lower()
    if d not in {"min", "max", "asc", "desc"}:
        return semantic_layer_dict
    text = (
        f"For '{metric}', prefer {d.upper()} when the question is ambiguous "
        "about which extreme is 'higher' or 'best'."
    )
    return record_learned_convention(semantic_layer_dict, text)
