from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.agent.catalog import identity_keys_from_tables, serialize_keys
from src.agent.verified_cache import find_verified_sql, token_overlap
from src.config.settings import get_settings
from src.context.business_rules import BusinessRulesStore
from src.context.golden_records import GoldenRecordsStore
from src.context.retrieval.index import (
    _FACT_TABLE_MIN_OUTGOING_FKS,
    _FK_EXPAND_MAX_DEPTH,
    _FK_EXPAND_MAX_EXTRA,
    _FORCE_FACT_FK_MAX,
    _JOIN_PATH_EXPAND_MAX,
    _build_fk_indegree,
    _dynamic_faiss_top_k,
    _expand_columns_for_huge_schema,
    _expand_fk_targets,
    _expand_via_join_paths,
    _force_fact_fk_targets,
    _relationship_edges_from_connection,
    _safe_json_loads,
    group_tables_by_pattern,
)
from src.context.retrieval.prompt import (
    _build_link_query,
    _expand_link_query,
    _format_history_for_linker,
)
from src.context.retrieval.scan import scan_connection_schema
from src.context.retrieval.schema_text_cache import (
    get_cached_schema_text,
    invalidate_schema_text,
    schema_version_token,
    set_cached_schema_text,
)
from src.context.schema_enrichment import SchemaEnrichmentStore
from src.context.schema_linker import SchemaLinker
from src.context.semantic_layer import append_semantic_to_rules
from src.context.value_grounding import (
    build_value_index,
    extract_literals,
    format_value_hints,
    match_literals_to_values,
)
from src.providers.database.base import BaseDatabaseProvider
from src.storage.models import Connection, SchemaCache

# Near-exact golden match threshold for verified_sql injection.
_VERIFIED_SQL_OVERLAP = 0.92


def _approx_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token) for schema budget checks."""
    return max(0, len(text or "") // 4)


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

        connection_row = await session.get(Connection, connection_id)
        if not caches:
            if connection_row is None:
                raise ValueError(f"Connection not found: {connection_id}")
            steps.append(
                {
                    "step": "schema_scan",
                    "detail": "Schema cache empty; scanning connection",
                }
            )
            caches = await scan_connection_schema(
                session, connection_row, db_provider
            )
            invalidate_schema_text(connection_id)

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
        version = schema_version_token(
            table_count=len(all_table_names),
            last_scanned_at=getattr(connection_row, "last_scanned_at", None),
            enrichment_count=sum(
                1
                for t in enrich_map.values()
                for _ in ([t] if t.get("description") else [])
            )
            + sum(len((t.get("columns") or {})) for t in enrich_map.values()),
            sample_rows=int(getattr(self._settings, "schema_sample_rows", 2) or 0),
        )
        full_schema_text = get_cached_schema_text(connection_id, version)
        if full_schema_text is None:
            full_schema_text = await self.enrichments.format_enriched_schema(
                session, connection_id, tables_data_all
            )
            set_cached_schema_text(connection_id, version, full_schema_text)
        else:
            steps.append(
                {
                    "step": "schema_text_cache",
                    "detail": "Reused cached formatted schema text",
                }
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
        if connection_row is None:
            connection_row = await session.get(Connection, connection_id)
        semantic_json = getattr(connection_row, "semantic_layer_json", None) if connection_row else None
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

        # 6. Verified-answer cache: near-exact golden → skip generation
        verified_sql = ""
        verified_min = float(
            getattr(self._settings, "verified_min_score", _VERIFIED_SQL_OVERLAP)
            or _VERIFIED_SQL_OVERLAP
        )
        # Prefer high-score FAISS hit from golden search; fall back to token overlap.
        best_hit = golden_hits[0] if golden_hits else None
        if (
            best_hit
            and float(best_hit.get("score") or 0) >= verified_min
            and (best_hit.get("sql") or "").strip()
        ):
            verified_sql = str(best_hit["sql"]).strip()
            used_golden = True
            if verified_sql not in golden_sqls:
                golden_sqls.insert(0, verified_sql)
            steps.append(
                {
                    "step": "verified_cache",
                    "detail": (
                        f"Verified SQL match "
                        f"(score={float(best_hit.get('score') or 0):.2f} "
                        f">= {verified_min})"
                    ),
                    "question": best_hit.get("question"),
                }
            )
        else:
            verified = await find_verified_sql(
                session,
                connection_id,
                question,
                min_overlap=verified_min,
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
                                f"(overlap={overlap:.2f} >= {verified_min})"
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
