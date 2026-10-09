from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.context.relationships import (
    discover_relationships,
    edges_to_semantic_join_paths,
    merge_relationship_edges,
)
from src.context.schema_labels import fk_label_hint
from src.context.semantic_layer import parse_semantic_layer
from src.storage.models import Connection, SchemaCache, SchemaEnrichment

logger = logging.getLogger(__name__)

# Sentinel so upsert can leave fields unchanged when omitted.
_UNSET: Any = object()


def _safe_json_loads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None


def _comment_parts(
    description: str | None = None,
    alias: str | None = None,
    example_values: Any = None,
    foreign_key: dict | None = None,
    *,
    target_columns: list[dict[str, Any]] | None = None,
) -> str:
    bits: list[str] = []
    if foreign_key:
        bits.append(
            fk_label_hint(foreign_key, target_columns=target_columns)
            or f"FK to {foreign_key.get('table')}.{foreign_key.get('column')}"
        )
    # Hide internal ddl: hashes stored in alias for change detection.
    if alias and not str(alias).startswith("ddl:"):
        bits.append(f"alias: {alias}")
    if description:
        bits.append(description)
    if example_values is not None:
        if isinstance(example_values, str):
            parsed = _safe_json_loads(example_values, default=example_values)
        else:
            parsed = example_values
        if parsed:
            bits.append(f"Values: {parsed}")
    return "; ".join(bits)


class SchemaEnrichmentStore:
    """CRUD + formatting for per-connection schema enrichments."""

    async def list(
        self, session: AsyncSession, connection_id: str
    ) -> list[SchemaEnrichment]:
        result = await session.execute(
            select(SchemaEnrichment)
            .where(SchemaEnrichment.connection_id == connection_id)
            .order_by(SchemaEnrichment.table_name, SchemaEnrichment.column_name)
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        session: AsyncSession,
        connection_id: str,
        table_name: str,
        column_name: str | None,
        description: Any = _UNSET,
        alias: Any = _UNSET,
        example_values: Any = _UNSET,
    ) -> SchemaEnrichment:
        stmt = select(SchemaEnrichment).where(
            SchemaEnrichment.connection_id == connection_id,
            SchemaEnrichment.table_name == table_name,
        )
        if column_name is None:
            stmt = stmt.where(SchemaEnrichment.column_name.is_(None))
        else:
            stmt = stmt.where(SchemaEnrichment.column_name == column_name)

        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        serialized_examples = example_values
        if example_values is not _UNSET and example_values is not None:
            if not isinstance(example_values, str):
                serialized_examples = json.dumps(example_values)
            else:
                serialized_examples = example_values

        if row is None:
            row = SchemaEnrichment(
                connection_id=connection_id,
                table_name=table_name,
                column_name=column_name,
                description=None if description is _UNSET else description,
                alias=None if alias is _UNSET else alias,
                example_values=(
                    None if example_values is _UNSET else serialized_examples
                ),
            )
            session.add(row)
        else:
            if description is not _UNSET:
                row.description = description
            if alias is not _UNSET:
                row.alias = alias
            if example_values is not _UNSET:
                row.example_values = serialized_examples

        await session.flush()
        return row

    async def delete(self, session: AsyncSession, id: str) -> bool:
        row = await session.get(SchemaEnrichment, id)
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True

    async def get_for_tables(
        self,
        session: AsyncSession,
        connection_id: str,
        table_names: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Return enrichments nested by table → {description, alias, columns}."""
        if not table_names:
            return {}

        result = await session.execute(
            select(SchemaEnrichment).where(
                SchemaEnrichment.connection_id == connection_id,
                SchemaEnrichment.table_name.in_(table_names),
            )
        )
        rows = result.scalars().all()

        out: dict[str, dict[str, Any]] = {
            name: {"description": None, "alias": None, "columns": {}}
            for name in table_names
        }
        for row in rows:
            bucket = out.setdefault(
                row.table_name,
                {"description": None, "alias": None, "columns": {}},
            )
            if row.column_name is None:
                bucket["description"] = row.description
                bucket["alias"] = row.alias
            else:
                bucket["columns"][row.column_name] = {
                    "description": row.description,
                    "alias": row.alias,
                    "example_values": _safe_json_loads(
                        row.example_values, default=row.example_values
                    ),
                }
        return out

    async def format_enriched_schema(
        self,
        session: AsyncSession,
        connection_id: str,
        tables_data: list[dict[str, Any]],
    ) -> str:
        """Build CREATE TABLE style text with enrichments and sample rows."""
        if not tables_data:
            return "(no schema)"

        table_names = [
            t.get("table_name") or t.get("name") for t in tables_data if t.get("table_name") or t.get("name")
        ]
        enrichments = await self.get_for_tables(session, connection_id, table_names)

        # Pull sample rows from schema cache when not already on the dict
        cache_by_name: dict[str, SchemaCache] = {}
        if table_names:
            result = await session.execute(
                select(SchemaCache).where(
                    SchemaCache.connection_id == connection_id,
                    SchemaCache.table_name.in_(table_names),
                )
            )
            for cache in result.scalars().all():
                cache_by_name[cache.table_name] = cache

        # Index columns by table so FK comments can list label columns on targets.
        columns_by_table: dict[str, list[dict[str, Any]]] = {}
        for table in tables_data:
            tname = table.get("table_name") or table.get("name")
            if not tname:
                continue
            cols = table.get("columns")
            if cols is None:
                cache = cache_by_name.get(tname)
                cols = _safe_json_loads(
                    cache.columns_json if cache else None, default=[]
                ) or []
            columns_by_table[str(tname)] = list(cols) if isinstance(cols, list) else []
        for tname, cache in cache_by_name.items():
            if tname not in columns_by_table:
                columns_by_table[tname] = (
                    _safe_json_loads(cache.columns_json, default=[]) or []
                )

        blocks: list[str] = []
        for table in tables_data:
            table_name = table.get("table_name") or table.get("name")
            if not table_name:
                continue

            enrichment = enrichments.get(table_name, {})
            table_desc = enrichment.get("description")
            table_alias = enrichment.get("alias")
            if table_alias and str(table_alias).startswith("ddl:"):
                table_alias = None
            col_enrich = enrichment.get("columns") or {}

            header_lines = [f"-- TABLE: {table_name}"]
            if table_alias:
                header_lines.append(f"-- Alias: {table_alias}")
            if table_desc:
                header_lines.append(f"-- Description: {table_desc}")

            columns = columns_by_table.get(str(table_name), [])

            col_entries: list[tuple[str, str]] = []  # (sql_part, comment)
            fk_lines: list[str] = []
            for col in columns:
                name = col.get("name") or col.get("column_name")
                if not name:
                    continue
                col_type = col.get("type") or col.get("data_type") or "UNKNOWN"
                parts = [f"    {name}  {col_type}"]
                if col.get("primary_key"):
                    parts.append("PRIMARY KEY")
                if col.get("nullable") is False and not col.get("primary_key"):
                    parts.append("NOT NULL")

                meta = col_enrich.get(name, {})
                fk = col.get("foreign_key")
                target_cols = None
                if isinstance(fk, dict):
                    target = fk.get("table") or fk.get("foreign_table_name")
                    if target:
                        target_cols = columns_by_table.get(str(target))
                comment = _comment_parts(
                    description=meta.get("description"),
                    alias=meta.get("alias"),
                    example_values=meta.get("example_values"),
                    foreign_key=fk if isinstance(fk, dict) else None,
                    target_columns=target_cols,
                )
                col_entries.append((" ".join(parts), comment))

                if fk:
                    fk_lines.append(
                        f"    FOREIGN KEY ({name}) REFERENCES "
                        f"{fk.get('table')}({fk.get('column')})"
                    )
                elif col.get("foreign_table_name") and col.get("foreign_column_name"):
                    fk_lines.append(
                        f"    FOREIGN KEY ({name}) REFERENCES "
                        f"{col['foreign_table_name']}({col['foreign_column_name']})"
                    )

            # Prefer explicit foreign_keys list when present
            for fk in table.get("foreign_keys") or []:
                col_name = fk.get("column_name") or fk.get("column")
                ref_table = fk.get("foreign_table_name") or fk.get("table")
                ref_col = fk.get("foreign_column_name") or (
                    fk.get("column") if "foreign_table_name" in fk else None
                )
                if col_name and ref_table and ref_col:
                    decl = (
                        f"    FOREIGN KEY ({col_name}) REFERENCES "
                        f"{ref_table}({ref_col})"
                    )
                    if decl not in fk_lines:
                        fk_lines.append(decl)

            body_lines: list[str] = []
            total = len(col_entries) + len(fk_lines)
            for i, (sql_part, comment) in enumerate(col_entries):
                is_last = i == total - 1
                suffix = "" if is_last else ","
                if comment:
                    body_lines.append(f"{sql_part}{suffix}  -- {comment}")
                else:
                    body_lines.append(f"{sql_part}{suffix}")
            for j, fk_line in enumerate(fk_lines):
                is_last = (len(col_entries) + j) == total - 1
                suffix = "" if is_last else ","
                body_lines.append(f"{fk_line}{suffix}")

            body = "\n".join(body_lines) if body_lines else "    -- (no columns)"
            ddl = f"CREATE TABLE {table_name} (\n{body}\n);"

            sample_rows = table.get("sample_rows")
            if sample_rows is None:
                cache = cache_by_name.get(table_name)
                sample_rows = _safe_json_loads(
                    cache.sample_rows_json if cache else None, default=[]
                ) or []

            # Compact samples: skip when most columns already have descriptions,
            # and cap to settings.schema_sample_rows (default 2).
            sample_block = ""
            try:
                from src.config.settings import get_settings

                max_samples = int(getattr(get_settings(), "schema_sample_rows", 2) or 0)
            except Exception:
                max_samples = 2
            described_cols = sum(
                1
                for c in columns
                if (col_enrich.get(c.get("name") or c.get("column_name") or {}) or {}).get(
                    "description"
                )
            )
            mostly_described = bool(columns) and described_cols >= max(
                1, int(0.6 * len(columns))
            )
            if sample_rows and max_samples > 0 and not mostly_described:
                sample_block = "\n" + _format_sample_rows(
                    table_name, list(sample_rows)[:max_samples]
                )

            blocks.append("\n".join(header_lines) + "\n" + ddl + sample_block)

        return "\n\n".join(blocks) if blocks else "(no schema)"


async def discover_and_merge_relationships(
    session: AsyncSession,
    connection: Connection,
    tables_data: list[dict[str, Any]],
    db_provider: Any = None,
    *,
    auto_approve: bool = True,
    max_probes: int = 50,
) -> list[dict[str, Any]]:
    """Run relationship discovery and merge edges into ``semantic_layer_json``.

    Called after schema scan / FK extraction. Best-effort: failures are logged
    and do not abort the scan. Declared FKs and name-suffix candidates are
    merged into ``relationships``; approved edges also refresh ``join_paths``.
    """
    if not tables_data:
        return []

    discovered = await discover_relationships(
        tables_data,
        db_provider,
        auto_approve=auto_approve,
        max_probes=max_probes,
    )
    if not discovered:
        return []

    layer = parse_semantic_layer(getattr(connection, "semantic_layer_json", None))
    existing = layer.get("relationships") if isinstance(layer.get("relationships"), list) else []
    merged = merge_relationship_edges(existing, discovered)
    layer["relationships"] = merged

    # Keep join_paths in sync for approved (and auto-approved) edges.
    path_set = {
        str(p).strip().lower()
        for p in (layer.get("join_paths") or [])
        if str(p).strip()
    }
    join_paths = list(layer.get("join_paths") or []) if isinstance(layer.get("join_paths"), list) else []
    for path in edges_to_semantic_join_paths(
        [e for e in merged if str(e.get("status") or "").lower() == "approved"]
    ):
        key = path.lower()
        if key not in path_set:
            path_set.add(key)
            join_paths.append(path)
    layer["join_paths"] = join_paths

    connection.semantic_layer_json = json.dumps(layer)
    await session.flush()
    logger.info(
        "Merged %d relationship edge(s) into semantic layer for connection %s",
        len(merged),
        connection.id,
    )
    return merged


def _format_sample_rows(table_name: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys: list[str] = []
    for row in rows:
        for k in row.keys():
            if k not in keys:
                keys.append(k)
    if not keys:
        return ""

    str_rows = [
        ["" if row.get(k) is None else str(row.get(k)) for k in keys] for row in rows
    ]
    widths = [len(k) for k in keys]
    for sr in str_rows:
        for i, cell in enumerate(sr):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: list[str]) -> str:
        return " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    header = fmt(keys)
    sep = "-|-".join("-" * w for w in widths)
    lines = [header, sep] + [fmt(sr) for sr in str_rows]
    return (
        f"/* Sample rows ({len(rows)} rows from {table_name}):\n"
        + "\n".join(lines)
        + "\n*/"
    )
