"""Result-set equality and SQL normalize for eval. No LLM."""

from __future__ import annotations

import math
import re
from collections import Counter
from itertools import permutations
from typing import Any, Optional

from src.agent.trust import normalize_sql

_FLOAT_TOL = 1e-6
_MAX_PERM_COLS = 8
_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


def sql_equal(left: Optional[str], right: Optional[str], dialect: str = "postgres") -> bool:
    if not (left or "").strip() or not (right or "").strip():
        return False
    return normalize_sql(left or "", dialect=dialect) == normalize_sql(
        right or "", dialect=dialect
    )


def gold_has_order_by(sql: Optional[str]) -> bool:
    """True when the gold SQL requests a specific row order."""
    text = (sql or "").strip()
    if not text:
        return False
    return bool(_ORDER_BY_RE.search(text))


def _cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        return value
    text = str(value)
    # Numeric strings from SQLite / drivers
    try:
        if "." in text or "e" in text.lower():
            f = float(text)
            if math.isfinite(f) and abs(f - round(f)) < _FLOAT_TOL:
                return int(round(f))
            return f
        return int(text)
    except (TypeError, ValueError):
        return text


def _cells_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= _FLOAT_TOL
    return a == b


def _row_tuple(row: Any, columns: list[str]) -> tuple[Any, ...]:
    if isinstance(row, dict):
        return tuple(_cell(row.get(c)) for c in columns)
    if isinstance(row, (list, tuple)):
        return tuple(_cell(v) for v in row)
    return (_cell(row),)


def _rows_as_value_lists(payload: dict) -> list[list[Any]]:
    columns = list(payload.get("columns") or [])
    rows = payload.get("rows") or []
    out: list[list[Any]] = []
    for row in rows:
        if isinstance(row, dict):
            # Prefer declared column order; fall back to values()
            if columns:
                keyed = {str(k): v for k, v in row.items()}
                keyed_l = {str(k).lower(): v for k, v in row.items()}
                vals = []
                for c in columns:
                    if c in keyed:
                        vals.append(_cell(keyed[c]))
                    elif str(c).lower() in keyed_l:
                        vals.append(_cell(keyed_l[str(c).lower()]))
                    else:
                        vals.append(None)
                out.append(vals)
            else:
                out.append([_cell(v) for v in row.values()])
        elif isinstance(row, (list, tuple)):
            out.append([_cell(v) for v in row])
        else:
            out.append([_cell(row)])
    return out


def _rows_match(
    left_rows: list[tuple[Any, ...]],
    right_rows: list[tuple[Any, ...]],
    *,
    order_sensitive: bool,
) -> bool:
    if len(left_rows) != len(right_rows):
        return False
    if order_sensitive:
        return all(
            all(_cells_equal(a, b) for a, b in zip(lr, rr))
            for lr, rr in zip(left_rows, right_rows)
        )
    # Multiset of rows (order-insensitive).
    def _key(row: tuple[Any, ...]) -> tuple[Any, ...]:
        # Round floats for stable sorting / grouping.
        parts: list[Any] = []
        for v in row:
            if isinstance(v, float):
                parts.append(round(v, 6))
            else:
                parts.append(v)
        return tuple(parts)

    from collections import Counter

    return Counter(_key(r) for r in left_rows) == Counter(_key(r) for r in right_rows)


def results_equal(left: Optional[dict], right: Optional[dict]) -> bool:
    """Strict compare: column names (case-insensitive) + unordered rows."""
    if not left or not right:
        return False
    left_cols = [str(c).lower() for c in (left.get("columns") or [])]
    right_cols = [str(c).lower() for c in (right.get("columns") or [])]
    if not left_cols or not right_cols:
        return False
    if sorted(left_cols) != sorted(right_cols):
        return False

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

    return _rows_match(left_rows, aligned_right, order_sensitive=False)


def results_equal_values(
    left: Optional[dict],
    right: Optional[dict],
    *,
    gold_sql: Optional[str] = None,
    order_sensitive: Optional[bool] = None,
) -> bool:
    """Spider-style denotation equality: ignore column names, match values.

    Tries column permutations when the column count matches. Row order is
    ignored unless ``order_sensitive`` is True or the gold SQL has ORDER BY.
    """
    if not left or not right:
        return False
    left_vals = _rows_as_value_lists(left)
    right_vals = _rows_as_value_lists(right)
    if not left_vals and not right_vals:
        # Both empty — treat as equal only if column counts agree or both zero.
        lc = len(left.get("columns") or [])
        rc = len(right.get("columns") or [])
        return lc == rc or (lc == 0 and rc == 0)
    if not left_vals or not right_vals:
        return False
    if len(left_vals) != len(right_vals):
        return False
    n_cols = len(left_vals[0])
    if n_cols == 0:
        return True
    if any(len(r) != n_cols for r in left_vals):
        return False
    if any(len(r) != n_cols for r in right_vals):
        # Column count mismatch between sides
        right_cols = len(right_vals[0])
        if right_cols != n_cols:
            return False

    if order_sensitive is None:
        order_sensitive = gold_has_order_by(gold_sql)

    left_tuples = [tuple(r) for r in left_vals]
    right_matrix = right_vals

    if n_cols > _MAX_PERM_COLS:
        # Fall back: sort cells within each row (loses column association).
        def bag(rows: list[list[Any]]) -> list[tuple[Any, ...]]:
            out = []
            for row in rows:
                key = tuple(
                    sorted(
                        (round(v, 6) if isinstance(v, float) else v for v in row),
                        key=lambda x: (str(type(x)), str(x)),
                    )
                )
                out.append(key)
            return out

        if order_sensitive:
            return bag(left_vals) == bag(right_matrix)
        from collections import Counter

        return Counter(bag(left_vals)) == Counter(bag(right_matrix))

    for perm in permutations(range(n_cols)):
        remapped = [tuple(row[i] for i in perm) for row in right_matrix]
        if _rows_match(left_tuples, remapped, order_sensitive=order_sensitive):
            return True
    return False


def results_equal_lenient(
    gold: Optional[dict],
    generated: Optional[dict],
    *,
    gold_sql: Optional[str] = None,
    order_sensitive: Optional[bool] = None,
) -> bool:
    """Lenient denotation: gold columns may be a subset of generated columns.

    Projects the generated result onto every combination of columns matching
    the gold width, then reuses values-only row matching. Headline score for
    leaderboards should remain ``results_equal_values``; this is diagnostic.
    """
    if not gold or not generated:
        return False
    # Exact values-only already covers equal column counts.
    if results_equal_values(
        gold, generated, gold_sql=gold_sql, order_sensitive=order_sensitive
    ):
        return True

    gold_vals = _rows_as_value_lists(gold)
    gen_vals = _rows_as_value_lists(generated)
    if not gold_vals and not gen_vals:
        return True
    if not gold_vals or not gen_vals:
        return False
    if len(gold_vals) != len(gen_vals):
        return False

    g_cols = len(gold_vals[0])
    r_cols = len(gen_vals[0])
    if g_cols == 0:
        return True
    if r_cols < g_cols:
        return False
    if any(len(r) != g_cols for r in gold_vals) or any(len(r) != r_cols for r in gen_vals):
        return False

    if order_sensitive is None:
        order_sensitive = gold_has_order_by(gold_sql)

    gold_tuples = [tuple(r) for r in gold_vals]
    # Cap combinations: C(r_cols, g_cols) * g_cols! via permutations of chosen indices.
    from itertools import combinations

    max_right = min(r_cols, _MAX_PERM_COLS + 2)
    if r_cols > max_right:
        # Fall back: bag-of-cells per row containment (weak).
        def bag(row: list[Any]) -> Counter:
            parts = []
            for v in row:
                if isinstance(v, float):
                    parts.append(round(v, 6))
                else:
                    parts.append(v)
            return Counter(parts)

        gold_bags = [bag(r) for r in gold_vals]
        gen_bags = [bag(r) for r in gen_vals]
        if order_sensitive:
            return all(
                all(gb[k] <= rb[k] for k in gb) for gb, rb in zip(gold_bags, gen_bags)
            )
        # Multiset match of bags where each gold bag is covered by some gen bag.
        unused = gen_bags[:]
        for gb in gold_bags:
            hit = None
            for i, rb in enumerate(unused):
                if all(gb[k] <= rb[k] for k in gb):
                    hit = i
                    break
            if hit is None:
                return False
            unused.pop(hit)
        return True

    for chosen in combinations(range(r_cols), g_cols):
        projected = [[row[i] for i in chosen] for row in gen_vals]
        for perm in permutations(range(g_cols)):
            remapped = [tuple(row[i] for i in perm) for row in projected]
            if _rows_match(gold_tuples, remapped, order_sensitive=order_sensitive):
                return True
    return False
