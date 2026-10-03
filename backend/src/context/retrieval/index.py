from __future__ import annotations

import json
from typing import Any

from src.context.relationships import shortest_join_path
from src.context.schema_labels import LABEL_COLUMN_NAMES, NAME_LIKE_COLUMNS
from src.context.semantic_layer import parse_semantic_layer
from src.storage.models import Connection, SchemaCache

# Cap how many FK-neighbor tables we add after fine_select.
_FK_EXPAND_MAX_EXTRA = 15
# Max FK-graph hop depth for neighbor expansion (BFS).
_FK_EXPAND_MAX_DEPTH = 3
# Outgoing FK count that marks a selected table as a "fact" table.
_FACT_TABLE_MIN_OUTGOING_FKS = 5
# Cap for force-including direct FK targets of fact tables.
_FORCE_FACT_FK_MAX = 8
# Re-export shared label vocab so existing imports keep working.
_LABEL_COLUMN_NAMES = LABEL_COLUMN_NAMES
_NAME_LIKE_COLUMNS = NAME_LIKE_COLUMNS
# Cap intermediate join tables added via relationship shortest-path.
_JOIN_PATH_EXPAND_MAX = 12


def _safe_json_loads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None

def group_tables_by_pattern(table_names: list[str]) -> dict[str, list[str]]:
    """Group tables that share a prefix/suffix pattern (e.g. sales_2020, sales_2021).

    Strips trailing year/numeric/date-like segments and groups by the remaining
    stem. Singleton groups are omitted.
    """
    import re

    groups: dict[str, list[str]] = {}
    for name in table_names:
        if not name:
            continue
        stem = re.sub(
            r"([_\-]?(?:19|20)\d{2}|[_\-]?\d{4}[_\-]?\d{2}(?:[_\-]?\d{2})?|[_\-]?\d+)$",
            "",
            name,
            flags=re.IGNORECASE,
        ).rstrip("_-")
        if not stem or stem == name:
            continue
        groups.setdefault(stem.lower(), []).append(name)
    return {k: sorted(v) for k, v in groups.items() if len(v) >= 2}


def _expand_columns_for_huge_schema(
    selected_tables: list[str],
    cache_by_name: dict[str, SchemaCache],
) -> list[dict]:
    """When fine_select returns no columns on huge schemas, keep PK/FK + name-like."""
    selected_columns: list[dict] = []
    for name in selected_tables:
        cache = cache_by_name.get(name)
        columns = _safe_json_loads(
            cache.columns_json if cache else None, default=[]
        ) or []
        for col in columns:
            if not isinstance(col, dict):
                continue
            col_name = col.get("name") or col.get("column_name")
            if not col_name:
                continue
            lower = str(col_name).lower()
            keep = (
                bool(col.get("primary_key"))
                or bool(col.get("foreign_key"))
                or lower in _NAME_LIKE_COLUMNS
                or lower.endswith("_name")
                or lower.endswith("_code")
            )
            if keep:
                selected_columns.append({"table": name, "column": str(col_name)})
    return selected_columns


def _relationship_edges_from_connection(
    connection: Connection | None,
    cache_by_name: dict[str, SchemaCache],
) -> list[dict]:
    """Load relationship edges from semantic layer, falling back to declared FKs."""
    edges: list[dict] = []
    if connection is not None:
        layer = parse_semantic_layer(getattr(connection, "semantic_layer_json", None))
        rels = layer.get("relationships") or []
        if isinstance(rels, list):
            for e in rels:
                if isinstance(e, dict):
                    edges.append(e)
    if edges:
        return edges

    # Fallback: structural FKs from schema cache.
    for tname, cache in cache_by_name.items():
        columns = _safe_json_loads(cache.columns_json, default=[]) or []
        for col in columns:
            if not isinstance(col, dict):
                continue
            fk = col.get("foreign_key")
            if not isinstance(fk, dict):
                continue
            cname = col.get("name") or col.get("column_name")
            tt = fk.get("table") or fk.get("foreign_table_name")
            tc = fk.get("column") or fk.get("foreign_column_name")
            if cname and tt and tc:
                edges.append(
                    {
                        "from_table": tname,
                        "from_col": str(cname),
                        "to_table": str(tt),
                        "to_col": str(tc),
                        "status": "approved",
                        "score": 1.0,
                        "evidence": ["declared_fk"],
                    }
                )
    return edges


def _expand_via_join_paths(
    selected_tables: list[str],
    edges: list[dict],
    *,
    max_extra: int = _JOIN_PATH_EXPAND_MAX,
) -> list[str]:
    """Add intermediate tables needed to connect selected tables via relationships."""
    if len(selected_tables) < 2 or not edges or max_extra <= 0:
        return list(selected_tables)

    ordered = list(selected_tables)
    selected_set = set(ordered)
    remaining = max_extra

    # Connect each subsequent selected table back to the growing component.
    component = {ordered[0]}
    for dest in ordered[1:]:
        if dest in component:
            continue
        path = shortest_join_path(edges, component, {dest})
        for edge in path:
            if remaining <= 0:
                break
            # edge: (from_table, from_col, to_table, to_col)
            for node in (edge[0], edge[2]):
                if node not in selected_set:
                    selected_set.add(node)
                    ordered.append(node)
                    remaining -= 1
                    if remaining <= 0:
                        break
            component.add(edge[0])
            component.add(edge[2])
        component.add(dest)

    return ordered


def _dynamic_faiss_top_k(table_count: int, default: int) -> int:
    """Scale FAISS candidate count by schema size for better large-DB recall."""
    if table_count < 100:
        return 30
    if table_count <= 400:
        return max(default, 50)
    return max(default, 80)


def _column_names(cache: SchemaCache | None) -> set[str]:
    if cache is None:
        return set()
    columns = _safe_json_loads(cache.columns_json, default=[]) or []
    names: set[str] = set()
    for col in columns:
        if not isinstance(col, dict):
            continue
        raw = col.get("name") or col.get("column_name")
        if raw:
            names.add(str(raw).lower())
    return names


def _is_label_table(cache: SchemaCache | None) -> bool:
    """True if the table has common human-readable label columns (metadata only)."""
    return bool(_column_names(cache) & _LABEL_COLUMN_NAMES)


def _outgoing_fk_targets(
    cache: SchemaCache | None,
    known: set[str],
) -> list[str]:
    """Return unique FK target table names from one cache row (order preserved)."""
    if cache is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    columns = _safe_json_loads(cache.columns_json, default=[]) or []
    for col in columns:
        if not isinstance(col, dict):
            continue
        fk = col.get("foreign_key")
        if not isinstance(fk, dict):
            continue
        target = fk.get("table") or fk.get("foreign_table_name")
        if isinstance(target, str) and target in known and target not in seen:
            seen.add(target)
            found.append(target)
    return found


def _build_fk_indegree(
    cache_by_name: dict[str, SchemaCache],
) -> dict[str, int]:
    """Count how many times each table is referenced as an FK target.

    High in-degree means the table is an authoritative entity that many other
    tables depend on. Zero in-degree usually means a leaf, derived, or secondary
    table. Purely structural — no business or naming assumptions.
    """
    indegree: dict[str, int] = {}
    for cache in cache_by_name.values():
        columns = _safe_json_loads(cache.columns_json, default=[]) or []
        for col in columns:
            if not isinstance(col, dict):
                continue
            fk = col.get("foreign_key")
            if not isinstance(fk, dict):
                continue
            target = fk.get("table") or fk.get("foreign_table_name")
            if isinstance(target, str) and target:
                indegree[target] = indegree.get(target, 0) + 1
    return indegree


def _fk_targets_from_tables(
    source_tables: list[str],
    cache_by_name: dict[str, SchemaCache],
    *,
    exclude: set[str],
) -> list[str]:
    """Collect unique FK target table names from the given sources (order preserved)."""
    known = set(cache_by_name.keys())
    found: list[str] = []
    seen: set[str] = set(exclude)

    for name in source_tables:
        for target in _outgoing_fk_targets(cache_by_name.get(name), known):
            if target not in seen:
                seen.add(target)
                found.append(target)
    return found


def _rank_fk_candidates(
    candidates: list[str],
    cache_by_name: dict[str, SchemaCache],
    fk_indegree: dict[str, int] | None = None,
) -> list[str]:
    """Prefer high in-degree (authoritative) then label-like lookup tables."""
    indegree = fk_indegree or {}
    return sorted(
        candidates,
        key=lambda t: (
            -indegree.get(t, 0),
            0 if _is_label_table(cache_by_name.get(t)) else 1,
            t,
        ),
    )


def _outgoing_fk_column_count(cache: SchemaCache | None) -> int:
    """Count columns that declare a foreign_key (not unique target tables)."""
    if cache is None:
        return 0
    count = 0
    columns = _safe_json_loads(cache.columns_json, default=[]) or []
    for col in columns:
        if not isinstance(col, dict):
            continue
        fk = col.get("foreign_key")
        if isinstance(fk, dict) and (fk.get("table") or fk.get("foreign_table_name")):
            count += 1
    return count


def _force_fact_fk_targets(
    selected_tables: list[str],
    cache_by_name: dict[str, SchemaCache],
    fk_indegree: dict[str, int],
    *,
    max_force: int = _FORCE_FACT_FK_MAX,
    min_outgoing: int = _FACT_TABLE_MIN_OUTGOING_FKS,
) -> list[str]:
    """Force-include direct FK targets of selected fact tables (high out-degree).

    Fact tables (many outgoing FK columns) almost always need their high
    in-degree entity targets for joins and labels. Returns only newly forced
    tables, sorted by in-degree descending, capped at ``max_force``.
    """
    if not selected_tables or max_force <= 0:
        return []

    known = set(cache_by_name.keys())
    selected_set = set(selected_tables)
    candidates: set[str] = set()

    for name in selected_tables:
        cache = cache_by_name.get(name)
        if _outgoing_fk_column_count(cache) < min_outgoing:
            continue
        for target in _outgoing_fk_targets(cache, known):
            if target not in selected_set:
                candidates.add(target)

    ranked = sorted(
        candidates,
        key=lambda t: (-fk_indegree.get(t, 0), t),
    )
    return ranked[:max_force]


def _expand_fk_targets(
    selected_tables: list[str],
    cache_by_name: dict[str, SchemaCache],
    *,
    fk_indegree: dict[str, int] | None = None,
    max_extra: int = _FK_EXPAND_MAX_EXTRA,
    max_depth: int = _FK_EXPAND_MAX_DEPTH,
) -> list[str]:
    """Add FK neighbor tables via BFS (depth-limited, capped) using SchemaCache only.

    At each hop, prefer high FK in-degree tables, then label-like lookup tables,
    so authoritative entity chains resolve before low-authority noise consumes
    the budget.
    """
    if not selected_tables or max_extra <= 0:
        return list(selected_tables)

    ordered = list(selected_tables)
    selected_set = set(ordered)
    remaining = max_extra
    # Frontier starts at the fine-selected set (depth 0).
    frontier = list(selected_tables)

    for _depth in range(max(1, max_depth)):
        if remaining <= 0 or not frontier:
            break
        candidates = _rank_fk_candidates(
            _fk_targets_from_tables(frontier, cache_by_name, exclude=selected_set),
            cache_by_name,
            fk_indegree,
        )
        newly_added: list[str] = []
        for target in candidates:
            if remaining <= 0:
                break
            if target in selected_set:
                continue
            selected_set.add(target)
            ordered.append(target)
            newly_added.append(target)
            remaining -= 1
        frontier = newly_added

    return ordered
