"""Generic data-dictionary importer into SchemaEnrichment.

Supports:
  - BIRD-style per-table CSV (column_name, column_description, value_description)
  - JSON / YAML maps: {table: {column: {description, alias, example_values}}}
  - Flat CSV with table_name, column_name, description columns

No business-specific hardcoding — all content comes from the supplied files.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.context.schema_enrichment import SchemaEnrichmentStore

logger = logging.getLogger(__name__)


def _load_yaml_or_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore

            return yaml.safe_load(text)
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML required for YAML dictionaries; pip/uv add pyyaml"
            ) from exc
    return json.loads(text)


def parse_bird_description_csv(path: Path) -> list[dict[str, Any]]:
    """Parse one BIRD database_description CSV into enrichment rows.

    BIRD CSVs vary; we accept columns containing 'original'/'column' for the
    name and 'description' / 'value' for text.
    """
    table = path.stem
    # Common pattern: <table>.csv
    if table.endswith("_description"):
        table = table[: -len("_description")]
    rows_out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        fields = {h.lower().strip(): h for h in reader.fieldnames if h}

        def _col(*names: str) -> Optional[str]:
            for n in names:
                if n in fields:
                    return fields[n]
            for key, orig in fields.items():
                for n in names:
                    if n in key:
                        return orig
            return None

        name_col = _col("original_column_name", "column_name", "column")
        desc_col = _col("column_description", "description", "desc")
        value_col = _col("value_description", "value_desc", "values")
        if not name_col:
            return []
        for raw in reader:
            col = str(raw.get(name_col) or "").strip()
            if not col or col.startswith("-"):
                continue
            desc_parts = []
            if desc_col and raw.get(desc_col):
                desc_parts.append(str(raw[desc_col]).strip())
            examples: list[str] = []
            if value_col and raw.get(value_col):
                val = str(raw[value_col]).strip()
                if val:
                    desc_parts.append(f"Values: {val}")
                    # Split common separators for example_values.
                    for part in val.replace(";", ",").split(","):
                        part = part.strip().strip("'\"")
                        if part and len(part) < 80:
                            examples.append(part)
            rows_out.append(
                {
                    "table_name": table,
                    "column_name": col,
                    "description": " | ".join(p for p in desc_parts if p) or None,
                    "example_values": examples[:20] or None,
                }
            )
    return rows_out


def parse_dictionary_file(path: Path) -> list[dict[str, Any]]:
    """Parse CSV/JSON/YAML into a list of enrichment upsert payloads."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        # Detect flat vs BIRD per-table.
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = {h.lower().strip() for h in (reader.fieldnames or []) if h}
        if "table_name" in fields or "table" in fields:
            return _parse_flat_csv(path)
        return parse_bird_description_csv(path)

    data = _load_yaml_or_json(path)
    out: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "table_name": str(
                        item.get("table_name") or item.get("table") or ""
                    ),
                    "column_name": item.get("column_name") or item.get("column"),
                    "description": item.get("description"),
                    "alias": item.get("alias"),
                    "example_values": item.get("example_values"),
                }
            )
        return out
    if isinstance(data, dict):
        for table, cols in data.items():
            if not isinstance(cols, dict):
                continue
            for col, meta in cols.items():
                if isinstance(meta, str):
                    out.append(
                        {
                            "table_name": str(table),
                            "column_name": str(col),
                            "description": meta,
                        }
                    )
                elif isinstance(meta, dict):
                    out.append(
                        {
                            "table_name": str(table),
                            "column_name": str(col),
                            "description": meta.get("description"),
                            "alias": meta.get("alias"),
                            "example_values": meta.get("example_values"),
                        }
                    )
    return out


def _parse_flat_csv(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            lower = {k.lower().strip(): v for k, v in raw.items() if k}
            table = str(lower.get("table_name") or lower.get("table") or "").strip()
            col = str(
                lower.get("column_name") or lower.get("column") or ""
            ).strip() or None
            if not table:
                continue
            out.append(
                {
                    "table_name": table,
                    "column_name": col,
                    "description": lower.get("description"),
                    "alias": lower.get("alias"),
                    "example_values": lower.get("example_values"),
                }
            )
    return out


async def import_dictionary_rows(
    session: AsyncSession,
    connection_id: str,
    rows: list[dict[str, Any]],
) -> int:
    """Upsert parsed rows into SchemaEnrichment. Returns count updated."""
    store = SchemaEnrichmentStore()
    n = 0
    for row in rows:
        table = str(row.get("table_name") or "").strip()
        if not table:
            continue
        col = row.get("column_name")
        col_name = str(col).strip() if col is not None and str(col).strip() else None
        kwargs: dict[str, Any] = {}
        if row.get("description") is not None:
            kwargs["description"] = row["description"]
        if row.get("alias") is not None:
            kwargs["alias"] = row["alias"]
        if row.get("example_values") is not None:
            kwargs["example_values"] = row["example_values"]
        if not kwargs:
            continue
        await store.upsert(
            session,
            connection_id,
            table,
            col_name,
            **kwargs,
        )
        n += 1
    await session.commit()
    return n


async def import_dictionary_path(
    session: AsyncSession,
    connection_id: str,
    path: str | Path,
) -> int:
    """Import a file or directory of dictionary files."""
    p = Path(path)
    rows: list[dict[str, Any]] = []
    if p.is_dir():
        for child in sorted(p.rglob("*")):
            if child.suffix.lower() in {".csv", ".json", ".yaml", ".yml"}:
                try:
                    rows.extend(parse_dictionary_file(child))
                except Exception as exc:
                    logger.warning("skip dictionary file %s: %s", child, exc)
    elif p.is_file():
        rows = parse_dictionary_file(p)
    else:
        raise FileNotFoundError(path)
    return await import_dictionary_rows(session, connection_id, rows)


async def import_bird_descriptions_for_db(
    session: AsyncSession,
    connection_id: str,
    db_id: str,
    root: Path | None = None,
) -> int:
    """Import BIRD database_description CSVs for one db_id when present."""
    from src.eval.bird_data import bird_root

    base = root or bird_root()
    candidates = [
        base / "database_description" / db_id,
        base / "dev_databases" / db_id / "database_description",
        base / "dev_databases" / db_id,
    ]
    total = 0
    for folder in candidates:
        if not folder.is_dir():
            continue
        csvs = list(folder.glob("*.csv"))
        if not csvs:
            continue
        for csv_path in csvs:
            try:
                rows = parse_bird_description_csv(csv_path)
                total += await import_dictionary_rows(session, connection_id, rows)
            except Exception as exc:
                logger.warning("BIRD CSV import failed %s: %s", csv_path, exc)
        if total:
            break
    return total
