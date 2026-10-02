"""Post-execute result-shape heuristics (warnings + optional empty retry).

EMPTY_RESULT retries are soft: the executor sets ``shape_retry`` (not a hard
execution error) and clears results so ``route_after_execute`` can regenerate
once. Only retry when ``retries < 1`` to avoid infinite empty loops.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import sqlglot
from sqlglot import exp

# Row count at/above this fraction of max_rows suggests an unfiltered join blowup.
_CARTESIAN_FRACTION = 0.9
_DUPLICATE_FRACTION = 0.5

_WHERE_OR_JOIN_FILTER = re.compile(
    r"\b(where|on|having)\b",
    re.IGNORECASE,
)


def _row_key(row: Any, columns: list[str]) -> tuple[Any, ...]:
    if isinstance(row, dict):
        keyed = {str(k).lower(): v for k, v in row.items()}
        return tuple(keyed.get(str(c).lower()) for c in columns)
    if isinstance(row, (list, tuple)):
        return tuple(row)
    return (row,)


def _sql_has_filter_predicate(sql: str, dialect: str = "postgres") -> bool:
    """True when the query has WHERE / JOIN ON / HAVING (light AST + text fallback)."""
    text = (sql or "").strip()
    if not text:
        return False
    try:
        tree = sqlglot.parse_one(text, dialect=dialect)
        if tree.find(exp.Where) or tree.find(exp.Having):
            return True
        for join in tree.find_all(exp.Join):
            if join.args.get("on") is not None:
                return True
        return False
    except Exception:
        return bool(_WHERE_OR_JOIN_FILTER.search(text))


def _all_null_rows(rows: list[Any], columns: list[str]) -> bool:
    if not rows or not columns:
        return False
    for row in rows:
        if isinstance(row, dict):
            keyed = {str(k).lower(): v for k, v in row.items()}
            vals = [keyed.get(str(c).lower()) for c in columns]
        elif isinstance(row, (list, tuple)):
            vals = list(row)
        else:
            vals = [row]
        if any(v is not None for v in vals):
            return False
    return True


def analyze_result_shape(
    *,
    sql: str,
    results: dict[str, Any],
    max_rows: int,
    dialect: str = "postgres",
    retries: int = 0,
) -> dict[str, Any]:
    """Compute shape warnings and whether to soft-retry on empty/suspicious results.

    Returns:
        warnings: list[str]
        should_retry_empty: bool — True only for first empty attempt (retries < 1)
        should_retry_suspicious: bool — all-NULL / implausible once (retries < 1)
        row_count: int
        duplicate_fraction: float
    """
    row_count = int(results.get("row_count") or 0)
    columns = list(results.get("columns") or [])
    rows = list(results.get("rows") or [])
    warnings: list[str] = []

    if row_count == 0:
        warnings.append("empty_result")

    # Possible cartesian: near max_rows with no WHERE/JOIN filter predicates.
    if (
        max_rows > 0
        and row_count >= int(max_rows * _CARTESIAN_FRACTION)
        and not _sql_has_filter_predicate(sql, dialect)
    ):
        warnings.append("possible_cartesian")

    duplicate_fraction = 0.0
    if row_count > 1 and columns:
        keys = [_row_key(r, columns) for r in rows]
        counts = Counter(keys)
        dup_rows = sum(n - 1 for n in counts.values() if n > 1)
        duplicate_fraction = dup_rows / row_count if row_count else 0.0
        # >50% of rows are duplicates of some other identical row.
        if duplicate_fraction > _DUPLICATE_FRACTION:
            warnings.append("duplicate_rows")

    if row_count > 0 and _all_null_rows(rows, columns):
        warnings.append("all_null")

    # Soft empty retry once only — see module docstring.
    should_retry_empty = row_count == 0 and int(retries or 0) < 1
    # Execution-feedback revision for suspicious non-empty results (once).
    should_retry_suspicious = (
        int(retries or 0) < 1
        and row_count > 0
        and (
            "all_null" in warnings
            or "possible_cartesian" in warnings
        )
    )

    return {
        "warnings": warnings,
        "should_retry_empty": should_retry_empty,
        "should_retry_suspicious": should_retry_suspicious,
        "row_count": row_count,
        "duplicate_fraction": duplicate_fraction,
    }


def empty_result_message(sql: str) -> str:
    return (
        "Query returned 0 rows. Re-check filters, joins, and literal values "
        f"against the schema. Previous SQL: {sql[:200]}"
    )


def suspicious_result_message(sql: str, warnings: list[str]) -> str:
    joined = ", ".join(warnings) if warnings else "suspicious_shape"
    return (
        f"Query result looks suspicious ({joined}). "
        "Revise filters, joins, aggregates, or selected columns. "
        f"Previous SQL: {sql[:200]}"
    )
