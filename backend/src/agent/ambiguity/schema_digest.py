"""Schema index and compact digest for prompts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _norm_name(name: str) -> str:
    return (name or "").strip().strip('"').lower()


def _split_table_column(ref: str) -> tuple[str, str]:
    text = (ref or "").strip()
    if "." in text:
        table, _, column = text.partition(".")
        return _norm_name(table), _norm_name(column)
    return "", _norm_name(text)


def build_schema_index(
    selected_tables: Iterable[str],
    selected_columns: Iterable[dict[str, Any]] | None = None,
    *,
    extra_columns_by_table: dict[str, Iterable[str]] | None = None,
) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """Return (tables, (table, column) pairs, bare column names)."""
    tables = {_norm_name(t) for t in selected_tables if _norm_name(t)}
    pairs: set[tuple[str, str]] = set()
    bare: set[str] = set()
    for item in selected_columns or []:
        if not isinstance(item, dict):
            continue
        table = _norm_name(str(item.get("table") or ""))
        column = _norm_name(str(item.get("column") or item.get("name") or ""))
        if column:
            bare.add(column)
        if table and column:
            pairs.add((table, column))
            tables.add(table)
    for table, cols in (extra_columns_by_table or {}).items():
        t = _norm_name(table)
        if not t:
            continue
        tables.add(t)
        for col in cols or []:
            c = _norm_name(str(col))
            if c:
                pairs.add((t, c))
                bare.add(c)
    return tables, pairs, bare

def _normalize_fk_edges(
    fk_edges: Iterable[Any] | None,
) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for edge in fk_edges or []:
        if isinstance(edge, dict):
            ft = str(edge.get("from_table") or "").strip()
            fc = str(edge.get("from_col") or edge.get("from_column") or "").strip()
            tt = str(edge.get("to_table") or "").strip()
            tc = str(edge.get("to_col") or edge.get("to_column") or "").strip()
        elif isinstance(edge, (tuple, list)) and len(edge) >= 4:
            ft, fc, tt, tc = (str(edge[0]).strip(), str(edge[1]).strip(),
                              str(edge[2]).strip(), str(edge[3]).strip())
        else:
            continue
        if not (ft and fc and tt and tc):
            continue
        key = (ft, fc, tt, tc)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _format_example_values(values: Iterable[Any], *, limit: int = 5) -> str:
    parts: list[str] = []
    for raw in list(values)[:limit]:
        if isinstance(raw, str):
            parts.append(raw)
        else:
            parts.append(repr(raw))
    return ", ".join(parts)


def build_schema_digest(
    selected_tables: Iterable[str],
    selected_columns: Iterable[dict[str, Any]] | None = None,
    *,
    table_descriptions: dict[str, str] | None = None,
    column_descriptions: dict[str, dict[str, str]] | None = None,
    fk_edges: Iterable[Any] | None = None,
    column_types: dict[str, dict[str, str]] | None = None,
    example_values: dict[str, dict[str, list]] | None = None,
    max_tables: int = 30,
    max_columns_per_table: int = 40,
) -> str:
    """Compact digest for prompts, with optional types/examples/FK edges."""
    cols_by_table: dict[str, list[str]] = {}
    for item in selected_columns or []:
        if not isinstance(item, dict):
            continue
        table = str(item.get("table") or "").strip()
        column = str(item.get("column") or item.get("name") or "").strip()
        if table and column:
            cols_by_table.setdefault(table, [])
            if column not in cols_by_table[table]:
                cols_by_table[table].append(column)

    lines: list[str] = []
    tables = list(selected_tables)[:max_tables]
    table_set = set(tables)
    for table in tables:
        desc = ""
        if table_descriptions and table in table_descriptions:
            desc = (table_descriptions.get(table) or "").strip()
        header = f"{table}" + (f" — {desc}" if desc else "")
        lines.append(header)
        cols = cols_by_table.get(table) or []
        # If fine-select omitted columns but types are known, surface them.
        if not cols and column_types and table in column_types:
            cols = list(column_types[table].keys())[:max_columns_per_table]
        col_descs = (column_descriptions or {}).get(table) or {}
        type_map = (column_types or {}).get(table) or {}
        ex_map = (example_values or {}).get(table) or {}
        for col in cols[:max_columns_per_table]:
            ctype = str(type_map.get(col) or "").strip()
            cdesc = (col_descs.get(col) or "").strip()
            examples = ex_map.get(col) or []
            type_part = f" ({ctype})" if ctype else ""
            ex_part = ""
            if examples:
                ex_part = f" e.g. {_format_example_values(examples, limit=5)}"
            if cdesc:
                lines.append(f"  - {col}{type_part}: {cdesc}{ex_part}")
            elif type_part or ex_part:
                lines.append(f"  - {col}{type_part}{ex_part}")
            else:
                lines.append(f"  - {col}")
        if not cols:
            lines.append("  - (columns not fine-selected)")

    edges = _normalize_fk_edges(fk_edges)
    if edges:
        lines.append("Relationships:")
        for ft, fc, tt, tc in edges:
            if table_set and ft not in table_set and tt not in table_set:
                continue
            lines.append(f"  - {ft}.{fc} → {tt}.{tc}")

    return "\n".join(lines) if lines else "(none)"
