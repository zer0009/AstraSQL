"""Result-set equality and SQL normalize for eval. No LLM."""

from __future__ import annotations

from typing import Any, Optional

from src.agent.trust import normalize_sql


def sql_equal(left: Optional[str], right: Optional[str], dialect: str = "postgres") -> bool:
    if not (left or "").strip() or not (right or "").strip():
        return False
    return normalize_sql(left or "", dialect=dialect) == normalize_sql(
        right or "", dialect=dialect
    )


def _cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    return str(value)


def _row_tuple(row: Any, columns: list[str]) -> tuple[Any, ...]:
    if isinstance(row, dict):
        return tuple(_cell(row.get(c)) for c in columns)
    if isinstance(row, (list, tuple)):
        return tuple(_cell(v) for v in row)
    return (_cell(row),)


def results_equal(left: Optional[dict], right: Optional[dict]) -> bool:
    """Compare two execute_readonly-style payloads (columns + rows).

    Column names are compared case-insensitively. Row order is ignored so
    missing ORDER BY does not fail an otherwise correct result.
    """
    if not left or not right:
        return False
    left_cols = [str(c).lower() for c in (left.get("columns") or [])]
    right_cols = [str(c).lower() for c in (right.get("columns") or [])]
    if not left_cols or not right_cols:
        return False
    if sorted(left_cols) != sorted(right_cols):
        return False

    # Align right rows to left column order.
    right_index = {c: i for i, c in enumerate(right_cols)}
    left_rows = [_row_tuple(r, left.get("columns") or []) for r in (left.get("rows") or [])]
    aligned_right: list[tuple[Any, ...]] = []
    raw_right = right.get("rows") or []
    for row in raw_right:
        if isinstance(row, dict):
            keyed = {str(k).lower(): v for k, v in row.items()}
            aligned_right.append(tuple(_cell(keyed.get(c)) for c in left_cols))
        elif isinstance(row, (list, tuple)):
            remapped = [row[right_index[c]] for c in left_cols]
            aligned_right.append(tuple(_cell(v) for v in remapped))
        else:
            aligned_right.append((_cell(row),))

    return sorted(left_rows) == sorted(aligned_right)
