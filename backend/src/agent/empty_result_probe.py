"""Literal-verification probe before empty-result regeneration."""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from src.context.value_grounding import (
    build_value_index,
    extract_literals,
    match_literals_fuzzy,
    match_literals_to_values,
)

_STRING_LIT = re.compile(r"'([^']*)'")


def extract_where_literals(sql: str, dialect: str | None = None) -> list[str]:
    """Return string / number literals used in WHERE/HAVING / JOIN ON filters."""
    text = (sql or "").strip()
    if not text:
        return []
    out: list[str] = []
    try:
        tree = sqlglot.parse_one(text, dialect=dialect or None)
        scopes: list[exp.Expression] = []
        for cls in (exp.Where, exp.Having):
            node = tree.find(cls)
            if node is not None:
                scopes.append(node)
        for join in tree.find_all(exp.Join):
            on = join.args.get("on")
            if on is not None:
                scopes.append(on)
        if not scopes:
            scopes = [tree]
        for scope in scopes:
            for node in scope.find_all(exp.Literal):
                raw = node.this if hasattr(node, "this") else None
                if raw is None:
                    continue
                val = str(raw).strip()
                if val:
                    out.append(val)
    except Exception:
        out.extend(_STRING_LIT.findall(text))
    seen: set[str] = set()
    uniq: list[str] = []
    for lit in out:
        key = lit.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(lit)
    return uniq


def unverified_literals(
    *,
    sql: str,
    question: str,
    enrich_map: dict[str, Any] | None,
    dialect: str | None = None,
) -> list[str]:
    """Return WHERE literals that do not appear in enrichment value samples."""
    literals = extract_where_literals(sql, dialect)
    if not literals:
        literals = extract_literals(question)
    if not literals:
        return []
    index = build_value_index(enrich_map or {})
    if not index:
        # No value index → cannot verify; allow a single soft retry.
        return list(literals)
    matched = match_literals_to_values(literals, index)
    if not matched:
        matched = match_literals_fuzzy(literals, index)
    matched_values = {
        str(m.get("literal") or m.get("value") or "").strip().lower()
        for m in matched
        if isinstance(m, dict)
    }
    return [
        lit
        for lit in literals
        if lit.strip().lower() not in matched_values
    ]


def should_retry_empty(
    *,
    sql: str,
    question: str,
    context: dict[str, Any] | None,
    dialect: str | None = None,
    enabled: bool = True,
) -> tuple[bool, str]:
    """Decide whether an empty result warrants regeneration.

    Returns ``(should_retry, reason)``. When all filter literals are verified
    against sample values, answer "no rows" honestly instead of regenerating.
    """
    if not enabled:
        return True, "literal_probe_disabled"
    enrich_map = None
    if isinstance(context, dict):
        examples = context.get("example_values") or {}
        if examples:
            enrich_map = {
                table: {
                    "columns": {
                        col: {"example_values": vals}
                        for col, vals in (cols or {}).items()
                    }
                }
                for table, cols in examples.items()
                if isinstance(cols, dict)
            }
    missing = unverified_literals(
        sql=sql,
        question=question,
        enrich_map=enrich_map,
        dialect=dialect,
    )
    if missing:
        return True, f"unverified_literals:{','.join(missing[:5])}"
    return False, "literals_verified_empty_is_valid"
