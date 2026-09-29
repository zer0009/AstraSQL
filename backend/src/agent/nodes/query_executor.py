from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.agent.provenance import clarify_or_none, clarify_unbound
from src.agent.sql_guards import find_bind_placeholders
from src.agent.state import AgentState
from src.agent.utils import (
    append_step,
    build_retry_context,
    classify_retry_type,
    get_configurable,
    max_retries,
)
from src.config.settings import get_settings


async def query_executor(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """EXPLAIN then execute read-only SQL; inject DB errors for retries."""
    cfg = get_configurable(config)
    db_provider = cfg.get("db_provider")
    settings = get_settings()
    sql = (state.get("corrected_sql") or state.get("sql") or "").strip()
    retries = int(state.get("retries") or 0)

    if db_provider is None:
        return {
            "error": "Missing db_provider in configurable",
            "steps": append_step(state, "execute_error", "db_provider missing"),
        }
    if not sql:
        return {
            "error": "No SQL to execute",
            "steps": append_step(state, "execute_error", "Empty SQL"),
        }

    dialect = (
        db_provider.sqlglot_dialect()
        if hasattr(db_provider, "sqlglot_dialect")
        else "postgres"
    )
    if find_bind_placeholders(sql):
        return clarify_unbound(state, sql, dialect)
    clarify = clarify_or_none(state, sql, dialect)
    if clarify is not None:
        return clarify

    explain_text = ""
    try:
        explain_text = await db_provider.explain_query(sql)
        steps = append_step(
            state,
            "explain_ok",
            "EXPLAIN succeeded",
            plan_preview=(explain_text or "")[:500],
        )
        state = {**state, "steps": steps}
    except Exception as exc:
        if find_bind_placeholders(sql) or classify_retry_type(
            error=str(exc)
        ) == "BIND_PARAMETER":
            return clarify_unbound(state, sql, dialect)
        message = f"EXPLAIN failed: {exc}"
        return _execution_failure(state, sql=sql, message=message, retries=retries)

    try:
        results = await db_provider.execute_readonly(
            sql, max_rows=settings.max_result_rows
        )
        row_count = int(results.get("row_count") or 0)
        return {
            "results": results,
            "error": None,
            "retry_context": "",
            "steps": append_step(
                state,
                "query_executed",
                f"Returned {row_count} row(s)",
                row_count=row_count,
                columns=results.get("columns") or [],
            ),
        }
    except Exception as exc:
        message = str(exc)
        if classify_retry_type(error=message) == "BIND_PARAMETER":
            return clarify_unbound(state, sql, dialect)
        return _execution_failure(state, sql=sql, message=message, retries=retries)


def _execution_failure(
    state: AgentState,
    *,
    sql: str,
    message: str,
    retries: int,
) -> dict[str, Any]:
    limit = max_retries()
    retry_type = classify_retry_type(error=message)
    if retry_type == "OTHER":
        retry_type = "EXECUTION_ERROR"
    steps = append_step(
        state,
        "execute_error",
        message,
        sql=sql,
        retries=retries,
        will_retry=retries < limit,
        retry_type=retry_type,
    )
    return {
        "error": message,
        "retry_context": build_retry_context(
            previous_sql=sql,
            error=message,
            prior_context=state.get("retry_context") or "",
            retry_type=retry_type,
        ),
        "steps": steps,
    }
