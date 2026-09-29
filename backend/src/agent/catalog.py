"""Identity keys from the introspected catalog. No name or language heuristics."""

from __future__ import annotations

from typing import Any, Iterable


def _norm(name: str) -> str:
    return (name or "").strip().strip('"').lower()


def _column_name(col: dict[str, Any]) -> str:
    return _norm(str(col.get("name") or col.get("column_name") or ""))


def _has_foreign_key(col: dict[str, Any]) -> bool:
    fk = col.get("foreign_key")
    if not isinstance(fk, dict):
        return False
    return bool(fk.get("table") or fk.get("foreign_table_name"))


def identity_keys(
    columns_by_table: dict[str, Iterable[dict[str, Any]]],
) -> set[tuple[str, str]]:
    """Return (table, column) pairs that are a primary key or a foreign key."""
    keys: set[tuple[str, str]] = set()
    for table, columns in (columns_by_table or {}).items():
        table_name = _norm(str(table))
        if not table_name:
            continue
        for col in columns or []:
            if not isinstance(col, dict):
                continue
            name = _column_name(col)
            if not name:
                continue
            if col.get("primary_key") or _has_foreign_key(col):
                keys.add((table_name, name))
    return keys


def identity_keys_from_tables(tables: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    """Build keys from retriever ``tables_data`` rows (table_name + columns)."""
    columns_by_table: dict[str, list[dict[str, Any]]] = {}
    for row in tables or []:
        if not isinstance(row, dict):
            continue
        name = row.get("table_name") or row.get("name")
        if not name:
            continue
        columns = row.get("columns") or []
        if isinstance(columns, list):
            columns_by_table[str(name)] = columns
    return identity_keys(columns_by_table)


def serialize_keys(keys: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"table": table, "column": column} for table, column in sorted(keys)]


def deserialize_keys(payload: Iterable[dict[str, Any]] | None) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        table = _norm(str(item.get("table") or ""))
        column = _norm(str(item.get("column") or ""))
        if table and column:
            keys.add((table, column))
    return keys
