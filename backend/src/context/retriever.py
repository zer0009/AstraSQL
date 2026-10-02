from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import sqlglot
from sqlglot import exp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.catalog import identity_keys_from_tables, serialize_keys
from src.agent.verified_cache import find_verified_sql, token_overlap
from src.config.settings import get_settings
from src.context.business_rules import BusinessRulesStore
from src.context.golden_records import GoldenRecordsStore
from src.context.relationships import shortest_join_path
from src.context.schema_enrichment import (
    SchemaEnrichmentStore,
    discover_and_merge_relationships,
)
from src.context.schema_linker import SchemaLinker
from src.context.semantic_layer import append_semantic_to_rules, parse_semantic_layer
from src.context.value_grounding import (
    build_value_index,
    extract_literals,
    format_value_hints,
    match_literals_to_values,
)
from src.providers.database.base import BaseDatabaseProvider
from src.storage.models import Connection, SchemaCache

logger = logging.getLogger(__name__)

# Cap how many FK-neighbor tables we add after fine_select.
_FK_EXPAND_MAX_EXTRA = 15
# Max FK-graph hop depth for neighbor expansion (BFS).
_FK_EXPAND_MAX_DEPTH = 3
# How many prior turns to fold into the FAISS / linker query text.
_LINK_HISTORY_TURNS = 3
# Outgoing FK count that marks a selected table as a "fact" table.
_FACT_TABLE_MIN_OUTGOING_FKS = 5
# Cap for force-including direct FK targets of fact tables.
_FORCE_FACT_FK_MAX = 8
# Generic column-name hints that a table is a human-label / lookup table.
_LABEL_COLUMN_NAMES = frozenset(
    {"name", "title", "label", "code", "display_name", "displayname"}
)
# Name-like columns to keep when expanding sparse fine_select on huge schemas.
_NAME_LIKE_COLUMNS = frozenset(
    {
        "name",
        "title",
        "label",
        "code",
        "description",
        "display_name",
        "displayname",
        "fullname",
        "slug",
    }
)
# Cap intermediate join tables added via relationship shortest-path.
_JOIN_PATH_EXPAND_MAX = 12


def _approx_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token) for schema budget checks."""
    return max(0, len(text or "") // 4)


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


# Near-exact golden match threshold for verified_sql injection.
_VERIFIED_SQL_OVERLAP = 0.92


@dataclass
class RetrievedContext:
    enriched_schema: str
    business_rules: str
    golden_records_text: str
    selected_tables: list[str]
    selected_columns: list[dict]
    identity_keys: list[dict] = field(default_factory=list)
    used_golden: bool = False
    golden_sqls: list[str] = field(default_factory=list)
    golden_questions: list[str] = field(default_factory=list)
    verified_sql: str = ""
    steps: list[dict] = field(default_factory=list)
    # Compact digest inputs (from SchemaCache columns_json + enrichments).
    fk_edges: list[tuple[str, str, str, str]] = field(default_factory=list)
    column_types: dict[str, dict[str, str]] = field(default_factory=dict)
    example_values: dict[str, dict[str, list]] = field(default_factory=dict)


def _safe_json_loads(raw: Optional[str], default: Any = None) -> Any:
    if raw is None or raw == "":
        return default if default is not None else None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else None


def _tables_from_sql(sql: str | None) -> list[str]:
    """Extract table names from SQL via sqlglot AST (dialect-agnostic best-effort)."""
    text = (sql or "").strip()
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    try:
        for tree in sqlglot.parse(text):
            if tree is None:
                continue
            for table in tree.find_all(exp.Table):
                name = table.name
                if name and name not in seen:
                    seen.add(name)
                    found.append(name)
    except Exception:
        return []
    return found


def _prior_tables_from_history(
    conversation_history: list[dict[str, Any]] | None,
    known_tables: set[str],
) -> list[str]:
    """Union of tables referenced in prior-turn SQL that exist in SchemaCache."""
    if not conversation_history:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for turn in conversation_history:
        if not isinstance(turn, dict):
            continue
        for name in _tables_from_sql(str(turn.get("sql") or "")):
            if name in known_tables and name not in seen:
                seen.add(name)
                found.append(name)
    return found


def _build_link_query(
    question: str,
    conversation_history: list[dict[str, Any]] | None,
    *,
    max_turns: int = _LINK_HISTORY_TURNS,
) -> str:
    """FAISS / linker query: current question + recent prior questions/answers."""
    parts: list[str] = [question.strip()] if question and question.strip() else []
    if conversation_history:
        for turn in conversation_history[-max_turns:]:
            if not isinstance(turn, dict):
                continue
            prior_q = str(turn.get("question") or "").strip()
            prior_a = str(turn.get("answer") or "").strip()
            if prior_q:
                parts.append(prior_q)
            if prior_a:
                # Keep answer snippets short so embedding stays focused.
                parts.append(prior_a[:200])
    return "\n".join(parts) if parts else question


def _format_history_for_linker(
    conversation_history: list[dict[str, Any]] | None,
    *,
    max_turns: int = _LINK_HISTORY_TURNS,
) -> str:
    """Compact history text for schema-link LLM prompts."""
    if not conversation_history:
        return ""
    blocks: list[str] = []
    for index, turn in enumerate(conversation_history[-max_turns:], start=1):
        if not isinstance(turn, dict):
            continue
        q = str(turn.get("question") or "").strip()
        if not q:
            continue
        a = str(turn.get("answer") or "").strip()
        line = f"Turn {index} — User: {q}"
        if a:
            line += f"\n  Answer: {a[:180]}"
        blocks.append(line)
    return "\n".join(blocks)


_QUERY_EXPAND_SYSTEM = """\
You expand natural-language data questions into richer search phrases for schema retrieval.
Do NOT invent specific table or column names from any product. Stay database-agnostic.

Given a user question, return a short expansion that:
1. Names the business entities involved (people, places, products, documents, etc.)
2. Lists likely database representations as generic concepts
   (e.g. "geographic state/province/region lookup", "customer/partner master data",
   "product/item catalog", "order/transaction line items")
3. Notes the relationship type (comparison, cross-join, grouping, trend, filter)

Return plain text only — a single line or short paragraph of search keywords.
No JSON, no markdown, no SQL.
"""


async def _expand_link_query(question: str) -> str:
    """LLM-enrich the FAISS query with entity synonyms (database-agnostic).

    Falls back to the original question on any failure so retrieval still runs.
    """
    text = (question or "").strip()
    if not text:
        return question

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.providers.llm import get_llm_provider

        settings = get_settings()
        model_name = (
            (settings.expansion_model or "").strip()
            or (settings.enrichment_model or "").strip()
            or None
        )
        chat = get_llm_provider().get_chat_model(
            temperature=0.0,
            max_tokens=256,
            model=model_name,
        )
        response = await chat.ainvoke(
            [
                SystemMessage(content=_QUERY_EXPAND_SYSTEM),
                HumanMessage(content=text),
            ]
        )
        content = response.content
        if isinstance(content, list):
            expanded = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            ).strip()
        else:
            expanded = str(content).strip()
        if not expanded:
            return text
        # Combine original + expansion so exact terms still match embeddings.
        return f"{text}\n{expanded}"
    except Exception:
        return text


async def scan_connection_schema(
    session: AsyncSession,
    connection: Connection,
    db_provider: BaseDatabaseProvider,
    *,
    rebuild_table_index: bool = True,
    progress: Optional[Callable[..., None]] = None,
) -> list[SchemaCache]:
    """List tables from the live DB, upsert SchemaCache rows, optionally rebuild FAISS.

    Reads from the target DB first, then writes to SQLite in one pass under
    ``no_autoflush`` so mid-loop SELECTs do not flush pending INSERTs and
    collide with concurrent SQLite readers (common "database is locked" cause).

    ``progress`` is an optional callback used by background scan jobs:
    ``progress(phase=..., message=..., current_table=..., tables_total=...,
               tables_done=..., table_just_done=...)``.
    """

    def _progress(**kwargs: Any) -> None:
        if progress is not None:
            progress(**kwargs)

    _progress(phase="listing", message="Listing tables…")
    tables = await db_provider.list_tables()
    names = []
    for t in tables:
        name = t.get("name") if isinstance(t, dict) else str(t)
        if name:
            names.append(name)

    _progress(
        phase="reading",
        message=f"Reading schema for {len(names)} tables…",
        tables_total=len(names),
        tables_done=0,
    )

    # Phase 1: pull everything from the remote DB (no SQLite writes yet).
    remote: list[tuple[str, str | None, str, str]] = []
    for i, name in enumerate(names):
        _progress(
            phase="reading",
            message=f"Reading table {i + 1}/{len(names)}: {name}",
            current_table=name,
            tables_total=len(names),
            tables_done=i,
        )
        schema = await db_provider.get_table_schema(name)
        try:
            ddl = await db_provider.get_table_ddl(name)
        except Exception:
            ddl = None
        columns_json = json.dumps(schema.get("columns") or [])
        sample_rows_json = json.dumps(
            schema.get("sample_rows") or [], default=str
        )
        remote.append((name, ddl, columns_json, sample_rows_json))
        _progress(
            phase="reading",
            message=f"Read {i + 1}/{len(names)}: {name}",
            current_table=name,
            tables_total=len(names),
            tables_done=i + 1,
            table_just_done=name,
        )

    # Phase 2: upsert into SQLite without query-invoked autoflush.
    _progress(
        phase="writing",
        message="Saving schema cache…",
        current_table=None,
        tables_total=len(names),
        tables_done=len(names),
    )
    upserted: list[SchemaCache] = []
    with session.no_autoflush:
        for name, ddl, columns_json, sample_rows_json in remote:
            result = await session.execute(
                select(SchemaCache).where(
                    SchemaCache.connection_id == connection.id,
                    SchemaCache.table_name == name,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = SchemaCache(
                    connection_id=connection.id,
                    table_name=name,
                    ddl_text=ddl,
                    columns_json=columns_json,
                    sample_rows_json=sample_rows_json,
                )
                session.add(row)
            else:
                row.ddl_text = ddl
                row.columns_json = columns_json
                row.sample_rows_json = sample_rows_json
            upserted.append(row)

        connection.last_scanned_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.flush()

    if rebuild_table_index:
        _progress(
            phase="indexing",
            message="Building table search index…",
            current_table=None,
        )
        linker = SchemaLinker()
        await linker.build_table_index(session, connection.id)

    # Best-effort value grounding for low-cardinality string columns.
    try:
        from src.context.value_grounding import populate_example_values

        _progress(
            phase="value_grounding",
            message="Sampling distinct values for categorical columns…",
            current_table=None,
        )
        await populate_example_values(
            session, connection.id, upserted, db_provider
        )
    except Exception:
        logger.exception(
            "Value grounding failed for connection %s (scan kept)",
            connection.id,
        )

    # Best-effort relationship discovery → semantic_layer_json.
    settings = get_settings()
    if settings.relationship_discovery_enabled:
        try:
            _progress(
                phase="relationships",
                message="Discovering join relationships…",
                current_table=None,
            )
            tables_data: list[dict[str, Any]] = []
            for name, _ddl, columns_json, sample_rows_json in remote:
                tables_data.append(
                    {
                        "table_name": name,
                        "columns": _safe_json_loads(columns_json, default=[]) or [],
                        "sample_rows": _safe_json_loads(sample_rows_json, default=[])
                        or [],
                    }
                )
            await discover_and_merge_relationships(
                session,
                connection,
                tables_data,
                db_provider,
                auto_approve=settings.relationship_auto_approve,
                max_probes=50,
            )
        except Exception:
            logger.exception(
                "Relationship discovery failed for connection %s (scan kept)",
                connection.id,
            )

    _progress(
        phase="done",
        message=f"Scan complete — {len(upserted)} tables",
        tables_done=len(upserted),
        tables_total=len(names),
        current_table=None,
    )
    return upserted


class ContextRetriever:
    """Orchestrates schema linking, enrichments, rules, and golden records."""

    def __init__(self) -> None:
        self.enrichments = SchemaEnrichmentStore()
        self.rules = BusinessRulesStore()
        self.golden = GoldenRecordsStore()
        self.linker = SchemaLinker()
        self._settings = get_settings()

    async def get(
        self,
        session: AsyncSession,
        connection_id: str,
        question: str,
        db_provider: BaseDatabaseProvider,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> RetrievedContext:
        steps: list[dict] = []

        # 1. Load schema cache (scan if empty)
        result = await session.execute(
            select(SchemaCache).where(SchemaCache.connection_id == connection_id)
        )
        caches = list(result.scalars().all())

        if not caches:
            connection = await session.get(Connection, connection_id)
            if connection is None:
                raise ValueError(f"Connection not found: {connection_id}")
            steps.append(
                {
                    "step": "schema_scan",
                    "detail": "Schema cache empty; scanning connection",
                }
            )
            caches = await scan_connection_schema(session, connection, db_provider)

        enrich_map = await self.enrichments.get_for_tables(
            session,
            connection_id,
            [c.table_name for c in caches],
        )

        all_table_names = [c.table_name for c in caches]
        cache_by_name = {c.table_name: c for c in caches}
        known_tables = set(all_table_names)

        # Prefetch full enriched schema for token-budget / full-schema policy.
        tables_data_all: list[dict[str, Any]] = []
        for name in all_table_names:
            cache = cache_by_name.get(name)
            tables_data_all.append(
                {
                    "table_name": name,
                    "columns": _safe_json_loads(
                        cache.columns_json if cache else None, default=[]
                    )
                    or [],
                    "sample_rows": _safe_json_loads(
                        cache.sample_rows_json if cache else None, default=[]
                    )
                    or [],
                }
            )
        full_schema_text = await self.enrichments.format_enriched_schema(
            session, connection_id, tables_data_all
        )
        full_tokens = _approx_tokens(full_schema_text)
        link_mode = (self._settings.schema_link_mode or "auto").strip().lower()
        token_budget = int(self._settings.schema_full_token_budget)
        use_full_schema = link_mode == "full" or (
            link_mode == "auto" and full_tokens <= token_budget
        )
        # "Huge" -> prefer FAISS coarse without LLM fine_select.
        large_threshold = int(self._settings.large_schema_table_threshold)
        schema_is_huge = (
            len(all_table_names) >= large_threshold or full_tokens > token_budget
        )
        # Pattern groups (partitioned/yearly tables) for coarse recall hints.
        table_patterns = group_tables_by_pattern(all_table_names)

        history_text = _format_history_for_linker(conversation_history)
        prior_tables = _prior_tables_from_history(
            conversation_history, known_tables
        )
        selected_tables: list[str] = []
        selected_columns: list[dict] = []
        skip_fk_expand = False
        # Golden FAISS search is independent of expansion; gather when both run.
        golden_hits: list[dict[str, str]] | None = None

        if use_full_schema:
            if schema_is_huge:
                link_query = _build_link_query(question, conversation_history)
                expanded_query, golden_hits = await asyncio.gather(
                    _expand_link_query(link_query),
                    self.golden.search(
                        session,
                        connection_id,
                        question,
                        top_k=self._settings.golden_records_top_k,
                    ),
                )
                top_k = _dynamic_faiss_top_k(
                    len(all_table_names),
                    self._settings.faiss_top_k_tables,
                )
                selected_tables = await self.linker.coarse_filter(
                    connection_id,
                    expanded_query,
                    all_table_names,
                    top_k=top_k,
                )
                for name in prior_tables:
                    if name not in selected_tables:
                        selected_tables.append(name)
                if table_patterns and selected_tables:
                    selected_lower = {t.lower() for t in selected_tables}
                    for members in table_patterns.values():
                        if any(m.lower() in selected_lower for m in members):
                            for m in members:
                                if m not in selected_tables:
                                    selected_tables.append(m)
                steps.append(
                    {
                        "step": "schema_coarse",
                        "detail": (
                            f"Full/auto path (huge schema): FAISS coarse only, "
                            f"{len(selected_tables)}/{len(all_table_names)} tables "
                            f"(~{full_tokens} tokens, budget={token_budget}, "
                            f"mode={link_mode}; skipped fine_select)"
                        ),
                        "tables": selected_tables,
                        "prior_tables": prior_tables,
                        "expanded_query": expanded_query[:300],
                        "schema_link_mode": link_mode,
                        "approx_tokens": full_tokens,
                    }
                )
            else:
                selected_tables = list(all_table_names)
                skip_fk_expand = True
                steps.append(
                    {
                        "step": "schema_full",
                        "detail": (
                            f"Passing full schema ({len(selected_tables)} tables, "
                            f"~{full_tokens} tokens <= budget {token_budget}; "
                            f"mode={link_mode}; skipped fine_select)"
                        ),
                        "tables": selected_tables,
                        "schema_link_mode": link_mode,
                        "approx_tokens": full_tokens,
                    }
                )
        else:
            # faiss mode, or auto over budget -> FAISS + LLM fine_select
            link_query = _build_link_query(question, conversation_history)
            expanded_query, golden_hits = await asyncio.gather(
                _expand_link_query(link_query),
                self.golden.search(
                    session,
                    connection_id,
                    question,
                    top_k=self._settings.golden_records_top_k,
                ),
            )

            top_k = _dynamic_faiss_top_k(
                len(all_table_names),
                self._settings.faiss_top_k_tables,
            )
            candidates = await self.linker.coarse_filter(
                connection_id,
                expanded_query,
                all_table_names,
                top_k=top_k,
            )
            for name in prior_tables:
                if name not in candidates:
                    candidates.append(name)

            steps.append(
                {
                    "step": "schema_coarse",
                    "detail": (
                        f"Coarse filter selected {len(candidates)} of "
                        f"{len(all_table_names)} tables (top_k={top_k}, "
                        f"mode={link_mode}, ~{full_tokens} tokens)"
                        + (
                            f" (+{len(prior_tables)} from prior SQL)"
                            if prior_tables
                            else ""
                        )
                    ),
                    "tables": candidates,
                    "prior_tables": prior_tables,
                    "expanded_query": expanded_query[:300],
                    "schema_link_mode": link_mode,
                    "approx_tokens": full_tokens,
                }
            )

            candidate_payload: list[dict[str, Any]] = []
            for name in candidates:
                cache = cache_by_name.get(name)
                columns = _safe_json_loads(
                    cache.columns_json if cache else None, default=[]
                ) or []
                table_enrich = enrich_map.get(name, {})
                col_enrich = table_enrich.get("columns") or {}
                enriched_cols = []
                for col in columns:
                    col_name = col.get("name") or col.get("column_name")
                    meta = col_enrich.get(col_name, {}) if col_name else {}
                    enriched_cols.append(
                        {
                            **col,
                            "description": meta.get("description")
                            or col.get("description"),
                        }
                    )
                candidate_payload.append(
                    {
                        "name": name,
                        "table_name": name,
                        "description": table_enrich.get("description") or "",
                        "columns": enriched_cols,
                    }
                )

            fine = await self.linker.fine_select(
                question,
                candidate_payload,
                conversation_history=history_text,
            )
            selected_tables = fine.get("tables") or []
            selected_columns = fine.get("columns") or []

            for name in prior_tables:
                if name not in selected_tables:
                    selected_tables.append(name)

            # Huge schemas: if fine_select left columns empty, expand PK/FK + name-like.
            if (
                schema_is_huge
                and selected_tables
                and not selected_columns
            ):
                selected_columns = _expand_columns_for_huge_schema(
                    selected_tables, cache_by_name
                )
                if selected_columns:
                    steps.append(
                        {
                            "step": "schema_column_expand",
                            "detail": (
                                f"Expanded {len(selected_columns)} PK/FK/name-like "
                                f"columns for huge schema "
                                f"(threshold={large_threshold})"
                            ),
                        }
                    )

            # Include patterned siblings when any member is selected (e.g. sales_2021).
            if table_patterns and selected_tables:
                selected_lower = {t.lower() for t in selected_tables}
                pattern_added: list[str] = []
                for members in table_patterns.values():
                    if any(m.lower() in selected_lower for m in members):
                        for m in members:
                            if m not in selected_tables:
                                selected_tables.append(m)
                                pattern_added.append(m)
                if pattern_added:
                    steps.append(
                        {
                            "step": "schema_pattern_expand",
                            "detail": (
                                f"Added {len(pattern_added)} patterned sibling "
                                f"table(s)"
                            ),
                            "tables": pattern_added[:20],
                        }
                    )

            steps.append(
                {
                    "step": "schema_fine",
                    "detail": (
                        f"Fine select linked {len(selected_tables)} tables, "
                        f"{len(selected_columns)} columns"
                    ),
                    "tables": selected_tables,
                    "columns": selected_columns,
                }
            )

        # Also expand columns on FAISS-only huge path when columns are empty.
        if (
            schema_is_huge
            and selected_tables
            and not selected_columns
            and use_full_schema
        ):
            selected_columns = _expand_columns_for_huge_schema(
                selected_tables, cache_by_name
            )
            if selected_columns:
                steps.append(
                    {
                        "step": "schema_column_expand",
                        "detail": (
                            f"Expanded {len(selected_columns)} PK/FK/name-like "
                            f"columns for huge FAISS path "
                            f"(threshold={large_threshold})"
                        ),
                    }
                )

        if not skip_fk_expand:
            before_expand = list(selected_tables)
            fk_indegree = _build_fk_indegree(cache_by_name)
            forced = _force_fact_fk_targets(
                selected_tables,
                cache_by_name,
                fk_indegree,
                max_force=_FORCE_FACT_FK_MAX,
                min_outgoing=_FACT_TABLE_MIN_OUTGOING_FKS,
            )
            if forced:
                selected_tables = list(selected_tables) + forced
                steps.append(
                    {
                        "step": "schema_fact_fk_force",
                        "detail": (
                            f"Force-included {len(forced)} high in-degree "
                            f"FK target(s) from fact tables "
                            f"(cap {_FORCE_FACT_FK_MAX})"
                        ),
                        "tables": forced,
                    }
                )

            selected_tables = _expand_fk_targets(
                selected_tables,
                cache_by_name,
                fk_indegree=fk_indegree,
                max_extra=_FK_EXPAND_MAX_EXTRA,
                max_depth=_FK_EXPAND_MAX_DEPTH,
            )
            added_fk = [t for t in selected_tables if t not in before_expand]
            if added_fk:
                steps.append(
                    {
                        "step": "schema_fk_expand",
                        "detail": (
                            f"Added {len(added_fk)} FK neighbor table(s) "
                            f"(BFS depth={_FK_EXPAND_MAX_DEPTH}, "
                            f"in-degree-ranked, cap {_FK_EXPAND_MAX_EXTRA})"
                        ),
                        "tables": added_fk,
                    }
                )

            # Expand intermediate join tables via discovered/declared relationships.
            connection_for_rels = await session.get(Connection, connection_id)
            rel_edges = _relationship_edges_from_connection(
                connection_for_rels, cache_by_name
            )
            before_join = list(selected_tables)
            selected_tables = _expand_via_join_paths(
                selected_tables,
                rel_edges,
                max_extra=_JOIN_PATH_EXPAND_MAX,
            )
            added_join = [t for t in selected_tables if t not in before_join]
            if added_join:
                steps.append(
                    {
                        "step": "schema_join_path_expand",
                        "detail": (
                            f"Added {len(added_join)} intermediate join table(s) "
                            f"via relationship shortest path "
                            f"(cap {_JOIN_PATH_EXPAND_MAX})"
                        ),
                        "tables": added_join,
                    }
                )

        # 3. Format enriched schema for selected tables (filter columns when known)
        cols_by_table: dict[str, set[str]] = {}
        for item in selected_columns:
            t = item.get("table")
            c = item.get("column")
            if t and c:
                cols_by_table.setdefault(t, set()).add(c)

        if (
            use_full_schema
            and not schema_is_huge
            and set(selected_tables) == set(all_table_names)
        ):
            enriched_schema = full_schema_text
            tables_data = tables_data_all
        else:
            tables_data = []
            for name in selected_tables:
                cache = cache_by_name.get(name)
                columns = _safe_json_loads(
                    cache.columns_json if cache else None, default=[]
                ) or []
                allowed = cols_by_table.get(name)
                if allowed:
                    filtered = []
                    for col in columns:
                        col_name = col.get("name") or col.get("column_name")
                        if (
                            col_name in allowed
                            or col.get("primary_key")
                            or col.get("foreign_key")
                        ):
                            filtered.append(col)
                    columns = filtered or columns

                sample_rows = _safe_json_loads(
                    cache.sample_rows_json if cache else None, default=[]
                ) or []
                tables_data.append(
                    {
                        "table_name": name,
                        "columns": columns,
                        "sample_rows": sample_rows,
                    }
                )

            enriched_schema = await self.enrichments.format_enriched_schema(
                session, connection_id, tables_data
            )

        # Digest inputs + value hints from enrichments / selected schema.
        column_types: dict[str, dict[str, str]] = {}
        fk_edges: list[tuple[str, str, str, str]] = []
        example_values: dict[str, dict[str, list]] = {}
        for entry in tables_data:
            name = entry.get("table_name") or entry.get("name")
            if not name:
                continue
            columns = entry.get("columns") or []
            for col in columns:
                if not isinstance(col, dict):
                    continue
                col_name = col.get("name") or col.get("column_name")
                if not col_name:
                    continue
                col_type = col.get("type") or col.get("data_type")
                if col_type:
                    column_types.setdefault(name, {})[str(col_name)] = str(col_type)
                fk = col.get("foreign_key")
                if isinstance(fk, dict):
                    to_table = fk.get("table") or fk.get("foreign_table_name")
                    to_col = fk.get("column") or fk.get("foreign_column_name")
                    if to_table and to_col:
                        edge = (name, str(col_name), str(to_table), str(to_col))
                        if edge not in fk_edges:
                            fk_edges.append(edge)

            col_enrich = (enrich_map.get(name) or {}).get("columns") or {}
            for col_name, meta in col_enrich.items():
                if not isinstance(meta, dict):
                    continue
                raw_ex = meta.get("example_values")
                if raw_ex is None:
                    continue
                if isinstance(raw_ex, str):
                    parsed = _safe_json_loads(raw_ex, default=None)
                    if parsed is None:
                        parsed = [raw_ex]
                    raw_ex = parsed
                if isinstance(raw_ex, list) and raw_ex:
                    example_values.setdefault(name, {})[str(col_name)] = list(
                        raw_ex
                    )[:5]

        value_index = build_value_index(enrich_map)
        literals = extract_literals(question)
        value_hints = match_literals_to_values(literals, value_index)
        if not value_hints and literals and value_index:
            # Fuzzy fallback for high-cardinality / near-match literals.
            from src.context.value_grounding import match_literals_fuzzy

            value_hints = match_literals_fuzzy(literals, value_index)
        hints_block = format_value_hints(value_hints)
        if hints_block:
            enriched_schema = f"{enriched_schema}\n\n{hints_block}"
            steps.append(
                {
                    "step": "value_hints",
                    "detail": f"Matched {len(value_hints)} value hint(s)",
                    "hints": value_hints[:8],
                }
            )

        steps.append(
            {
                "step": "enrichment",
                "detail": f"Formatted enriched schema for {len(tables_data)} tables",
            }
        )

        # 4. Business rules + optional semantic layer
        business_rules = await self.rules.get_rules_text(session, connection_id)
        connection_row = await session.get(Connection, connection_id)
        semantic_json = getattr(connection_row, "semantic_layer_json", None)
        business_rules = append_semantic_to_rules(business_rules, semantic_json)
        steps.append(
            {
                "step": "business_rules",
                "detail": (
                    "Loaded business rules"
                    if business_rules != "(none)"
                    else "No business rules"
                ),
            }
        )

        # 5. Golden records (may already have run in parallel with expansion)
        if golden_hits is None:
            golden_hits = await self.golden.search(
                session,
                connection_id,
                question,
                top_k=self._settings.golden_records_top_k,
            )
        golden_records_text = self.golden.format_few_shot(golden_hits)
        used_golden = len(golden_hits) > 0
        golden_sqls = [str(h.get("sql") or "") for h in golden_hits if h.get("sql")]
        golden_questions = [
            str(h.get("question") or "") for h in golden_hits if h.get("question")
        ]
        steps.append(
            {
                "step": "golden_records",
                "detail": f"Retrieved {len(golden_hits)} similar golden records",
                "used_golden": used_golden,
            }
        )

        # 6. Verified-answer cache: near-exact golden → trust certified SQL
        verified_sql = ""
        verified = await find_verified_sql(
            session,
            connection_id,
            question,
            min_overlap=_VERIFIED_SQL_OVERLAP,
        )
        if verified is not None:
            sql_text = (verified.sql or "").strip()
            if sql_text:
                overlap = token_overlap(question, verified.question or "")
                verified_sql = sql_text
                used_golden = True
                if sql_text not in golden_sqls:
                    golden_sqls.insert(0, sql_text)
                steps.append(
                    {
                        "step": "verified_cache",
                        "detail": (
                            f"Verified SQL match "
                            f"(overlap={overlap:.2f} >= {_VERIFIED_SQL_OVERLAP})"
                        ),
                        "question": verified.question,
                    }
                )

        return RetrievedContext(
            enriched_schema=enriched_schema,
            business_rules=business_rules,
            golden_records_text=golden_records_text,
            selected_tables=selected_tables,
            selected_columns=selected_columns,
            identity_keys=serialize_keys(
                identity_keys_from_tables(
                    [
                        {
                            "table_name": cache.table_name,
                            "columns": _safe_json_loads(
                                cache.columns_json, default=[]
                            )
                            or [],
                        }
                        for cache in caches
                    ]
                )
            ),
            used_golden=used_golden,
            golden_sqls=golden_sqls,
            golden_questions=golden_questions,
            verified_sql=verified_sql,
            steps=steps,
            fk_edges=fk_edges,
            column_types=column_types,
            example_values=example_values,
        )
