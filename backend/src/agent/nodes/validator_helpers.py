from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from src.agent.state import AgentState
from src.agent.utils import (
    append_step,
    build_retry_context,
    classify_retry_type,
    max_retries,
)
from src.context.schema_labels import unreadable_fk_dimension_issues


def _norm(name: str) -> str:
    return (name or "").strip().strip('"').strip("`").strip("[]").lower()


def check_catalog(
    sql: str,
    sqlglot_dialect: str,
    *,
    selected_tables: list[str] | None,
    selected_columns: list[dict] | None,
) -> list[str]:
    """Optional deterministic catalog check against context selections.

    Skips silently when selected_tables / selected_columns are unavailable.
    """
    tables = {_norm(t) for t in (selected_tables or []) if _norm(t)}
    col_pairs: set[tuple[str, str]] = set()
    bare_cols: set[str] = set()
    for item in selected_columns or []:
        if not isinstance(item, dict):
            continue
        t = _norm(str(item.get("table") or ""))
        c = _norm(str(item.get("column") or item.get("name") or ""))
        if c:
            bare_cols.add(c)
        if t and c:
            col_pairs.add((t, c))
            tables.add(t)

    if not tables and not bare_cols:
        return []

    try:
        tree = sqlglot.parse_one(sql, dialect=sqlglot_dialect)
    except Exception:
        return []

    issues: list[str] = []
    # Alias → physical table for qualified column checks.
    alias_map: dict[str, str] = {}
    for src in tree.find_all(exp.Table):
        name = _norm(src.name)
        if not name:
            continue
        alias = _norm(src.alias_or_name)
        if alias:
            alias_map[alias] = name
        alias_map[name] = name
        if tables and name not in tables:
            issues.append(f"Unknown table not in selected context: {src.name}")

    if bare_cols or col_pairs:
        for col in tree.find_all(exp.Column):
            cname = _norm(col.name)
            if not cname or cname == "*":
                continue
            table_ref = _norm(col.table) if col.table else ""
            if table_ref:
                physical = alias_map.get(table_ref, table_ref)
                if col_pairs and (physical, cname) not in col_pairs:
                    # Allow if bare name is selected (linker sometimes omits table).
                    if cname not in bare_cols:
                        issues.append(
                            f"Unknown column not in selected context: "
                            f"{table_ref}.{col.name}"
                        )
            elif bare_cols and cname not in bare_cols:
                # Unqualified — only flag when we have a bare-column allow-list.
                issues.append(
                    f"Unknown column not in selected context: {col.name}"
                )

    return issues


def check_readable_dimensions(
    sql: str,
    sqlglot_dialect: str,
    *,
    enriched_schema: str,
) -> list[str]:
    """Deterministic flag: raw FK ids in SELECT/GROUP BY when labels exist."""
    return unreadable_fk_dimension_issues(
        sql,
        dialect=sqlglot_dialect,
        enriched_schema=enriched_schema,
    )


def _pass_without_llm(
    state: AgentState,
    *,
    sql: str,
    mode: str,
    catalog_issues: list[str] | None = None,
) -> dict[str, Any]:
    detail = f"SQL validated ({mode}; LLM skipped)"
    if catalog_issues:
        detail = f"SQL validated ({mode}; catalog OK)"
    return {
        "sql": sql,
        "corrected_sql": sql,
        "error": None,
        "steps": append_step(
            state,
            "sql_validated",
            detail,
            issues=catalog_issues or [],
            is_valid=True,
            error_type=None,
            sql=sql,
            validator_mode=mode,
        ),
    }


def _fail_or_retry(
    state: AgentState,
    *,
    sql: str,
    message: str,
    retries: int,
    is_dml: bool,
    issues: list | None = None,
    retry_type: str | None = None,
) -> dict[str, Any]:
    """Set error/retry_context; exhaust retries immediately for DML blocks."""
    limit = max_retries()
    typed = classify_retry_type(
        error=message,
        issues=issues,
        error_type=retry_type,
        is_syntax=(retry_type == "SYNTAX_ERROR"),
    )
    steps = list(state.get("steps") or [])
    if not steps or steps[-1].get("name") not in {
        "validate_syntax_failed",
        "validate_retry",
        "validate_failed",
    }:
        steps = append_step(
            state,
            "validate_failed" if is_dml or retries >= limit else "validate_retry",
            message,
            sql=sql,
            issues=issues or [],
            retry_type=typed,
        )

    if is_dml:
        return {
            "error": message,
            "retries": limit,
            "retry_context": "",
            "steps": steps,
        }

    retry_ctx = build_retry_context(
        previous_sql=sql,
        error=message,
        prior_context=state.get("retry_context") or "",
        retry_type=typed,
    )
    return {
        "error": message,
        "retry_context": retry_ctx,
        "steps": steps,
    }
