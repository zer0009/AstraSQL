"""Deterministic SQL guards that do not rely on the LLM."""

from __future__ import annotations

import re
from typing import Optional

import sqlglot
from sqlglot import exp

_TABLE_HEADER_RE = re.compile(r"^--\s*TABLE:\s*(\S+)", re.IGNORECASE)
# Matches: "    name  VARCHAR(64)," or "    name  character varying -- ..."
_COL_DECL_RE = re.compile(
    r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
    r"([A-Za-z][A-Za-z0-9_(),\s]*?)"
    r"(?:\s+PRIMARY|\s+NOT NULL|,|\s*--|$)",
    re.IGNORECASE,
)


def parse_column_types(enriched_schema: str) -> dict[tuple[str, str], str]:
    """Parse ``(table, column) -> type`` from enriched CREATE TABLE text."""
    types: dict[tuple[str, str], str] = {}
    current_table: Optional[str] = None
    for line in (enriched_schema or "").splitlines():
        header = _TABLE_HEADER_RE.match(line.strip())
        if header:
            current_table = header.group(1)
            continue
        if not current_table:
            continue
        # Skip FK lines and comments
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("--")
            or stripped.upper().startswith("FOREIGN KEY")
            or stripped.startswith("CREATE TABLE")
            or stripped in {"(", ");", ")"}
        ):
            continue
        match = _COL_DECL_RE.match(line)
        if not match:
            continue
        col_name = match.group(1)
        col_type = match.group(2).strip().rstrip(",")
        types[(current_table.lower(), col_name.lower())] = col_type
    return types


def _is_json_type(type_str: str | None) -> bool:
    if not type_str:
        return False
    base = type_str.strip().lower().split("(", 1)[0].strip()
    return base in {"json", "jsonb"}


def _is_definitely_non_json(type_str: str | None) -> bool:
    if not type_str:
        return False
    if _is_json_type(type_str):
        return False
    base = type_str.strip().lower().split("(", 1)[0].strip()
    # Anything we successfully typed that is not json/jsonb is non-json.
    return bool(base) and base not in {"unknown", ""}


def _alias_to_table(tree: exp.Expression) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        name = (table.name or "").strip()
        if not name:
            continue
        mapping[name.lower()] = name
        alias = (table.alias_or_name or "").strip()
        if alias:
            mapping[alias.lower()] = name
    return mapping


def _resolve_column_type(
    column: exp.Expression,
    *,
    alias_map: dict[str, str],
    column_types: dict[tuple[str, str], str],
) -> str | None:
    if not isinstance(column, exp.Column):
        return None
    col_name = (column.name or "").strip().lower()
    if not col_name:
        return None
    table_ref = (column.table or "").strip().lower()
    if table_ref:
        real_table = alias_map.get(table_ref, table_ref)
        return column_types.get((real_table.lower(), col_name))

    # Unqualified: unique match across schema only.
    matches = [t for (tbl, c), t in column_types.items() if c == col_name]
    # Actually values are types; need unique table
    tables = [tbl for (tbl, c) in column_types if c == col_name]
    if len(tables) == 1:
        return column_types.get((tables[0], col_name))
    return None


def rewrite_invalid_json_operators(
    sql: str,
    *,
    dialect: str,
    enriched_schema: str,
) -> tuple[str, list[str]]:
    """Replace ``col ->> key`` / ``col -> key`` with ``col`` when col is non-JSON.

    Returns ``(sql, issues)``. Issues is empty when no rewrite was needed.
    """
    text = (sql or "").strip()
    if not text or ("->" not in text):
        return text, []

    column_types = parse_column_types(enriched_schema)
    if not column_types:
        return text, []

    try:
        tree = sqlglot.parse_one(text, dialect=dialect)
    except Exception:
        return text, []

    alias_map = _alias_to_table(tree)
    issues: list[str] = []

    for node in list(tree.find_all(exp.JSONExtractScalar, exp.JSONExtract)):
        base = node.this
        col_type = _resolve_column_type(
            base, alias_map=alias_map, column_types=column_types
        )
        if not _is_definitely_non_json(col_type):
            continue
        # Replace JSON operator expression with the bare column / expression.
        replacement = base.copy()
        node.replace(replacement)
        issues.append(
            f"Removed JSON operator from non-JSON column "
            f"({base.sql(dialect=dialect)} typed {col_type})"
        )

    if not issues:
        return text, []

    try:
        rewritten = tree.sql(dialect=dialect)
    except Exception:
        return text, []
    return rewritten, issues
