"""Value grounding: sample low-cardinality column values and match question literals."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.context.schema_enrichment import SchemaEnrichmentStore
from src.providers.database.base import BaseDatabaseProvider
from src.storage.models import SchemaCache

logger = logging.getLogger(__name__)

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PII_NAME_HINTS = ("email", "phone", "ssn", "password", "secret", "token")
_STRING_TYPE_HINTS = (
    "char",
    "text",
    "string",
    "enum",
    "uuid",
    "varchar",
    "nvarchar",
    "nchar",
    "clob",
    "name",
    "citext",
)
_NON_STRING_TYPE_HINTS = (
    "int",
    "float",
    "double",
    "decimal",
    "numeric",
    "bool",
    "bit",
    "date",
    "time",
    "timestamp",
    "blob",
    "binary",
    "bytea",
    "real",
    "money",
    "serial",
    "json",
    "jsonb",
)

# Quoted strings, then bare numbers (for literal extraction).
_QUOTED_RE = re.compile(
    r"'([^']*)'"
    r'|"([^"]*)"'
)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def _safe_json_loads(raw: Optional[str], default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None


def looks_like_pii(column_name: str) -> bool:
    """True when the column name suggests PII / secrets (skip value grounding)."""
    lower = (column_name or "").strip().lower()
    if not lower:
        return False
    return any(hint in lower for hint in _PII_NAME_HINTS)


def is_string_like_type(col_type: str | None) -> bool:
    """Heuristic: string / categorical types suitable for distinct-value samples."""
    t = (col_type or "").strip().lower()
    if not t:
        return True
    if any(h in t for h in _STRING_TYPE_HINTS):
        return True
    if any(h in t for h in _NON_STRING_TYPE_HINTS):
        return False
    return True


def _quote_ident(name: str, dialect: str) -> str | None:
    if not _SAFE_IDENT.match(name or ""):
        return None
    d = (dialect or "").lower()
    if d in ("mysql", "tsql"):
        return f"`{name}`" if d == "mysql" else f"[{name}]"
    return f'"{name}"'


def extract_literals(question: str) -> list[str]:
    """Extract quoted strings and numeric literals from a natural-language question."""
    text = question or ""
    found: list[str] = []
    seen: set[str] = set()

    for match in _QUOTED_RE.finditer(text):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        if value is None:
            continue
        value = value.strip()
        if not value:
            continue
        key = value.lower()
        if key not in seen:
            seen.add(key)
            found.append(value)

    # Strip quoted spans before scanning bare numbers.
    stripped = _QUOTED_RE.sub(" ", text)
    for match in _NUMBER_RE.finditer(stripped):
        value = match.group(0)
        key = value.lower()
        if key not in seen:
            seen.add(key)
            found.append(value)

    return found


def match_literals_to_values(
    literals: list[str],
    value_index: dict[str, list[str]],
) -> list[dict[str, str]]:
    """Match question literals to grounded column values (case-insensitive).

    ``value_index`` maps ``"table.column"`` → list of example values.
    Returns short hint dicts: ``{literal, table, column, value}``.
    """
    if not literals or not value_index:
        return []

    # Pre-index values → locations
    by_value: dict[str, list[tuple[str, str, str]]] = {}
    for key, values in value_index.items():
        if not isinstance(values, (list, tuple)):
            continue
        if "." in key:
            table, column = key.split(".", 1)
        else:
            table, column = "", key
        for raw in values:
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            by_value.setdefault(text.lower(), []).append((table, column, text))

    hints: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for lit in literals:
        lit_text = str(lit).strip()
        if not lit_text:
            continue
        matches = by_value.get(lit_text.lower()) or []
        for table, column, value in matches:
            sig = (table, column, value.lower())
            if sig in seen:
                continue
            seen.add(sig)
            hints.append(
                {
                    "literal": lit_text,
                    "table": table,
                    "column": column,
                    "value": value,
                }
            )
    return hints


def build_value_index(enrich_map: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Build ``table.column → [values]`` from nested enrichment map."""
    index: dict[str, list[str]] = {}
    for table_name, meta in (enrich_map or {}).items():
        columns = (meta or {}).get("columns") or {}
        if not isinstance(columns, dict):
            continue
        for col_name, col_meta in columns.items():
            if not isinstance(col_meta, dict):
                continue
            raw = col_meta.get("example_values")
            if raw is None:
                continue
            if isinstance(raw, str):
                parsed = _safe_json_loads(raw, default=None)
            else:
                parsed = raw
            if not isinstance(parsed, list) or not parsed:
                continue
            values = [str(v) for v in parsed if v is not None and str(v).strip()]
            if values:
                index[f"{table_name}.{col_name}"] = values
    return index


def format_value_hints(hints: list[dict[str, str]], *, max_hints: int = 8) -> str:
    """Render a short 'Value hints:' block for the generator context."""
    if not hints:
        return ""
    lines = ["Value hints:"]
    for hint in hints[:max_hints]:
        table = hint.get("table") or "?"
        column = hint.get("column") or "?"
        value = hint.get("value") or hint.get("literal") or ""
        lines.append(f"- {table}.{column} ≈ {value!r}")
    return "\n".join(lines)


async def populate_example_values(
    session: AsyncSession,
    connection_id: str,
    caches: list[SchemaCache],
    db_provider: BaseDatabaseProvider,
    *,
    max_distinct: int | None = None,
) -> int:
    """Query distinct values for low-cardinality string columns; store on enrichments.

    Skips PII-looking column names. Caps at ``value_grounding_max_distinct``.
    Returns the number of columns updated.
    """
    settings = get_settings()
    limit = (
        int(settings.value_grounding_max_distinct)
        if max_distinct is None
        else int(max_distinct)
    )
    if limit <= 0 or not caches:
        return 0

    store = SchemaEnrichmentStore()
    dialect = ""
    try:
        dialect = db_provider.sqlglot_dialect()
    except Exception:
        dialect = ""

    updated = 0
    for cache in caches:
        columns = _safe_json_loads(cache.columns_json, default=[]) or []
        table_q = _quote_ident(cache.table_name, dialect)
        if table_q is None:
            continue

        for col in columns:
            if not isinstance(col, dict):
                continue
            col_name = col.get("name") or col.get("column_name")
            if not col_name or looks_like_pii(str(col_name)):
                continue
            col_type = col.get("type") or col.get("data_type") or ""
            if not is_string_like_type(str(col_type)):
                continue
            col_q = _quote_ident(str(col_name), dialect)
            if col_q is None:
                continue

            sql = (
                f"SELECT DISTINCT {col_q} AS v FROM {table_q} "
                f"WHERE {col_q} IS NOT NULL "
                f"LIMIT {limit + 1}"
            )
            try:
                result = await db_provider.execute_readonly(sql, max_rows=limit + 1)
            except Exception:
                logger.debug(
                    "value grounding skip %s.%s (query failed)",
                    cache.table_name,
                    col_name,
                    exc_info=True,
                )
                continue

            rows = result.get("rows") or []
            values: list[str] = []
            for row in rows:
                if isinstance(row, dict):
                    raw = row.get("v")
                    if raw is None and row:
                        raw = next(iter(row.values()), None)
                elif isinstance(row, (list, tuple)) and row:
                    raw = row[0]
                else:
                    raw = row
                if raw is None:
                    continue
                text = str(raw).strip()
                if text and text not in values:
                    values.append(text)

            if not values or len(values) > limit:
                continue

            await store.upsert(
                session,
                connection_id=connection_id,
                table_name=cache.table_name,
                column_name=str(col_name),
                example_values=values[:limit],
            )
            updated += 1

    if updated:
        await session.flush()
    return updated
