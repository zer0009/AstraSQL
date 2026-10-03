"""Deterministic SQLite SQL repairs via sqlglot. No LLM."""

from __future__ import annotations

import sqlglot
from sqlglot import exp


def _is_integer_like(node: exp.Expression) -> bool:
    """True for integer literals or bare columns (SQLite affinity heuristic)."""
    if isinstance(node, exp.Literal):
        if node.is_string:
            return False
        text = node.this if isinstance(node.this, str) else str(node.this)
        try:
            int(text)
            return True
        except (TypeError, ValueError):
            return False
    if isinstance(node, exp.Column):
        return True
    if isinstance(node, exp.Paren):
        return _is_integer_like(node.this) if node.this is not None else False
    return False


def _already_cast_to_real(node: exp.Expression) -> bool:
    if isinstance(node, exp.Cast):
        to = node.args.get("to")
        if to is None:
            return False
        raw = getattr(to, "this", None)
        # sqlglot may use DataType.Type / DType enums — coerce via name/str.
        if raw is not None and not isinstance(raw, str):
            raw = getattr(raw, "name", None) or str(raw)
        type_name = str(raw or to or "").upper()
        return any(t in type_name for t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"))
    if isinstance(node, exp.Paren) and node.this is not None:
        return _already_cast_to_real(node.this)
    return False


def cast_integer_division(sql: str, *, dialect: str = "sqlite") -> tuple[str, bool]:
    """Wrap integer-like division operands so SQLite uses real division.

    Rewrites ``a / b`` to ``CAST(a AS REAL) / b`` when neither side is already
    CAST to a floating type and both look integer-like.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return sql, False

    changed = False

    for div in list(tree.find_all(exp.Div)):
        left = div.left
        right = div.right
        if left is None or right is None:
            continue
        if _already_cast_to_real(left) or _already_cast_to_real(right):
            continue
        if not (_is_integer_like(left) and _is_integer_like(right)):
            continue
        div.set("this", exp.cast(left.copy(), "REAL"))
        changed = True

    if not changed:
        return sql, False
    return tree.sql(dialect=dialect), True


def ensure_group_by_for_aggregates(sql: str, *, dialect: str = "sqlite") -> tuple[str, bool]:
    """Best-effort: add GROUP BY for bare SELECT columns mixed with aggregates.

    Skips when parse fails, when GROUP BY already exists, or when there are no
    aggregates / no bare columns to group.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return sql, False

    if not isinstance(tree, exp.Select):
        # Prefer outermost select when wrapped
        select = tree.find(exp.Select)
        if select is None:
            return sql, False
        tree = select

    if tree.args.get("group"):
        return sql, False

    agg_types = (
        exp.AggFunc,
        exp.Count,
        exp.Sum,
        exp.Avg,
        exp.Min,
        exp.Max,
        exp.GroupConcat,
    )
    has_agg = any(isinstance(n, agg_types) for n in tree.find_all(*agg_types))
    if not has_agg:
        # Also catch generic Aggregate subclasses
        has_agg = any(isinstance(n, exp.AggFunc) for n in tree.walk())
    if not has_agg:
        for n in tree.find_all(exp.Anonymous):
            name = (n.name or "").upper()
            if name in {"COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP_CONCAT", "TOTAL"}:
                has_agg = True
                break
    if not has_agg:
        return sql, False

    # Columns that appear under an aggregate should not be grouped.
    under_agg: set[int] = set()
    for agg in tree.find_all(exp.AggFunc, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max):
        for child in agg.walk():
            under_agg.add(id(child))

    group_exprs: list[exp.Expression] = []
    seen: set[str] = set()
    for proj in tree.expressions:
        # Skip pure aggregate projections
        if isinstance(proj, (exp.Alias, exp.AggFunc, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
            inner = proj.this if isinstance(proj, exp.Alias) else proj
            if isinstance(inner, (exp.AggFunc, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
                continue
            # Alias of non-agg expression — treat as group candidate
            if isinstance(proj, exp.Alias) and id(inner) not in under_agg:
                key = inner.sql(dialect=dialect)
                if key not in seen:
                    seen.add(key)
                    group_exprs.append(inner.copy())
                continue
        if isinstance(proj, exp.Column) and id(proj) not in under_agg:
            key = proj.sql(dialect=dialect)
            if key not in seen:
                seen.add(key)
                group_exprs.append(proj.copy())
            continue
        # Mixed expression with nested columns outside aggregates
        bare_cols = [
            c
            for c in proj.find_all(exp.Column)
            if id(c) not in under_agg and (c.name or "").strip() not in ("", "*")
        ]
        if bare_cols and not isinstance(proj, (exp.AggFunc, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
            # If the whole projection is an aggregate wrapping, skip
            root = proj.this if isinstance(proj, exp.Alias) else proj
            if isinstance(root, (exp.AggFunc, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
                continue
            for c in bare_cols:
                key = c.sql(dialect=dialect)
                if key not in seen:
                    seen.add(key)
                    group_exprs.append(c.copy())

    if not group_exprs:
        return sql, False

    tree.set("group", exp.Group(expressions=group_exprs))
    # Re-parse from root if we mutated a nested select — rewrite whole SQL from original
    try:
        root = sqlglot.parse_one(sql, dialect=dialect)
        # If tree was the root select, use it; else find and replace is hard — use mutated tree if root
        if isinstance(root, exp.Select):
            out_sql = tree.sql(dialect=dialect)
        else:
            out_sql = tree.sql(dialect=dialect)
        # Sanity: must still parse
        sqlglot.parse_one(out_sql, dialect=dialect)
        return out_sql, True
    except Exception:
        return sql, False


def normalize_year_filter(sql: str, *, dialect: str = "sqlite") -> tuple[str, bool]:
    """Optional year-extraction normalize — currently a no-op when unsure."""
    _ = dialect
    return sql, False


def repair_sqlite_sql(sql: str) -> tuple[str, list[str]]:
    """Apply deterministic SQLite repairs. Returns (sql, list of applied tags)."""
    text = (sql or "").strip()
    if not text:
        return sql, []

    tags: list[str] = []
    current = text

    repaired, ok = cast_integer_division(current, dialect="sqlite")
    if ok:
        current = repaired
        tags.append("cast_integer_division")

    repaired, ok = ensure_group_by_for_aggregates(current, dialect="sqlite")
    if ok:
        current = repaired
        tags.append("ensure_group_by_for_aggregates")

    repaired, ok = normalize_year_filter(current, dialect="sqlite")
    if ok:
        current = repaired
        tags.append("normalize_year_filter")

    return current, tags
