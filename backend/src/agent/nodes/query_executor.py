from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.agent.provenance import clarify_or_none, clarify_unbound
from src.agent.result_shape import (
    analyze_result_shape,
    empty_result_message,
    suspicious_result_message,
)
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
    """EXPLAIN then execute read-only SQL; inject DB errors for retries.
    After a successful execute, run light result-shape checks. Empty results
    soft-retry once via ``shape_retry`` (see ``result_shape`` module) so the
    graph regenerates without treating the empty set as a hard DB failure.
    """
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
    # Reuse results already produced by the ambiguity gate / candidate picker.
    prior = state.get("results") if isinstance(state.get("results"), dict) else None
    if (
        state.get("cached_execution")
        and prior
        and prior.get("columns") is not None
        and "row_count" in prior
    ):
        row_count = int(prior.get("row_count") or 0)
        return {
            "results": prior,
            "error": None,
            "shape_retry": False,
            "cached_execution": False,
            "retry_context": "",
            "steps": append_step(
                state,
                "query_executed",
                f"Reused gated result ({row_count} row(s))",
                row_count=row_count,
                columns=prior.get("columns") or [],
                reused_cached_execution=True,
            ),
        }
    if not hasattr(db_provider, "sqlglot_dialect"):
        return {
            "error": "db_provider missing sqlglot_dialect()",
            "steps": append_step(
                state, "execute_error", "db_provider missing sqlglot_dialect"
            ),
        }
    dialect = db_provider.sqlglot_dialect()
    if find_bind_placeholders(sql, dialect):
        return clarify_unbound(state, sql, dialect)
    clarify = clarify_or_none(state, sql, dialect)
    if clarify is not None:
        return clarify
    explain_text = ""
    supports_explain = True
    if hasattr(db_provider, "supports_explain"):
        supports_explain = bool(db_provider.supports_explain())
    if supports_explain:
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
            if find_bind_placeholders(sql, dialect) or classify_retry_type(
                error=str(exc)
            ) == "BIND_PARAMETER":
                return clarify_unbound(state, sql, dialect)
            message = f"EXPLAIN failed: {exc}"
            return _execution_failure(state, sql=sql, message=message, retries=retries)
    else:
        state = {
            **state,
            "steps": append_step(
                state,
                "explain_skipped",
                "EXPLAIN not supported by provider",
            ),
        }
    # Optional EXPLAIN cost gate (settings.explain_cost_limit > 0).
    cost_limit = float(getattr(settings, "explain_cost_limit", 0) or 0)
    if cost_limit > 0 and hasattr(db_provider, "estimate_cost"):
        try:
            estimated = await db_provider.estimate_cost(sql)
        except Exception:
            estimated = None
        if estimated is not None and float(estimated) > cost_limit:
            message = (
                f"Estimated query cost {estimated} exceeds limit {cost_limit}"
            )
            return _execution_failure(
                state, sql=sql, message=message, retries=retries
            )
    try:
        results = await db_provider.execute_readonly(
            sql, max_rows=settings.max_result_rows
        )
        row_count = int(results.get("row_count") or 0)
        shape = analyze_result_shape(
            sql=sql,
            results=results,
            max_rows=settings.max_result_rows,
            dialect=dialect,
            retries=retries,
        )
        warnings = list(shape.get("warnings") or [])
        # Soft EMPTY_RESULT retry once only when literals look unverified.
        if shape.get("should_retry_empty"):
            from src.agent.empty_result_probe import should_retry_empty

            do_retry, probe_why = should_retry_empty(
                sql=sql,
                question=str(state.get("question") or ""),
                context=state.get("context")
                if isinstance(state.get("context"), dict)
                else None,
                dialect=dialect,
                enabled=bool(
                    getattr(settings, "empty_result_literal_probe", True)
                ),
            )
            if do_retry:
                message = empty_result_message(sql)
                exploration = await _exploration_block(state, db_provider, settings)
                return {
                    "results": {},
                    "error": None,
                    "shape_retry": True,
                    "retry_context": build_retry_context(
                        previous_sql=sql,
                        error=f"{message} ({probe_why})",
                        prior_context="",
                        retry_type="EMPTY_RESULT",
                        exploration_block=exploration,
                    ),
                    "steps": append_step(
                        state,
                        "shape_retry_empty",
                        f"{message} [{probe_why}]",
                        sql=sql,
                        row_count=0,
                        warnings=warnings,
                        retry_type="EMPTY_RESULT",
                        probe=probe_why,
                    ),
                }
            # Literals verified → accept honest empty answer.
            return {
                "results": results,
                "error": None,
                "shape_retry": False,
                "retry_context": "",
                "steps": append_step(
                    state,
                    "query_executed",
                    f"Returned 0 row(s) (accepted; {probe_why})",
                    row_count=0,
                    columns=results.get("columns") or [],
                    shape_warnings=warnings,
                    probe=probe_why,
                ),
            }
        
        if shape.get("should_retry_suspicious"):
            message = suspicious_result_message(sql, warnings)
            return {
                "results": {},
                "error": None,
                "shape_retry": True,
                "retry_context": build_retry_context(
                    previous_sql=sql,
                    error=message,
                    prior_context=state.get("retry_context") or "",
                    retry_type="SUSPICIOUS_RESULT",
                ),
                "steps": append_step(
                    state,
                    "shape_retry_suspicious",
                    message,
                    sql=sql,
                    row_count=row_count,
                    warnings=warnings,
                    retry_type="SUSPICIOUS_RESULT",
                ),
            }
        return {
            "results": results,
            "error": None,
            "shape_retry": False,
            "retry_context": "",
            "steps": append_step(
                state,
                "query_executed",
                f"Returned {row_count} row(s)",
                row_count=row_count,
                columns=results.get("columns") or [],
                shape_warnings=warnings,
            ),
        }
    except Exception as exc:
        message = str(exc)
        if classify_retry_type(error=message) == "BIND_PARAMETER":
            return clarify_unbound(state, sql, dialect)
        # Bounded repair agent before falling back to regenerate.
        if bool(getattr(settings, "repair_agent_enabled", True)) and retries < 1:
            try:
                from src.agent.repair_agent import run_repair_agent

                repair = await run_repair_agent(
                    state=state,
                    db_provider=db_provider,
                    settings=settings,
                    error=message,
                )
                repaired = str(repair.get("sql") or "").strip()
                if repaired and repaired != sql:
                    try:
                        results = await db_provider.execute_readonly(
                            repaired, max_rows=settings.max_result_rows
                        )
                        row_count = int(results.get("row_count") or 0)
                        return {
                            "sql": repaired,
                            "corrected_sql": repaired,
                            "results": results,
                            "error": None,
                            "shape_retry": False,
                            "retry_context": "",
                            "steps": append_step(
                                state,
                                "repair_agent_ok",
                                f"Repair agent fixed SQL ({row_count} row(s))",
                                sql=repaired,
                                observations=repair.get("observations") or [],
                                steps_used=repair.get("steps_used"),
                            ),
                        }
                    except Exception as repair_exc:
                        message = f"{message}; repair_try_failed: {repair_exc}"
                        exploration = "\n".join(
                            str(x) for x in (repair.get("observations") or [])[:8]
                        )
                        return _execution_failure(
                            state,
                            sql=repaired,
                            message=message,
                            retries=retries,
                            exploration_block=exploration,
                        )
            except Exception as repair_outer:
                logger = __import__("logging").getLogger(__name__)
                logger.warning("repair_agent failed open: %s", repair_outer)
        exploration = await _exploration_block(state, db_provider, settings)
        return _execution_failure(
            state,
            sql=sql,
            message=message,
            retries=retries,
            exploration_block=exploration,
        )
def _tables_columns_for_explore(state: AgentState) -> list[tuple[str, str]]:
    """Pick a few table.column pairs from context for repair exploration."""
    context = state.get("context") or {}
    pairs: list[tuple[str, str]] = []
    for item in context.get("selected_columns") or []:
        if not isinstance(item, dict):
            continue
        table = str(item.get("table") or "").strip()
        column = str(item.get("column") or item.get("name") or "").strip()
        if table and column:
            pairs.append((table, column))
        if len(pairs) >= 6:
            break
    if pairs:
        return pairs
    for table in context.get("selected_tables") or []:
        t = str(table).strip()
        if t:
            pairs.append((t, "id"))
        if len(pairs) >= 3:
            break
    return pairs
async def _exploration_block(
    state: AgentState, db_provider: Any, settings: Any
) -> str:
    if not bool(getattr(settings, "column_exploration_enabled", True)):
        return ""
    try:
        from src.agent.column_explore import explore_for_repair
        return await explore_for_repair(
            db_provider, _tables_columns_for_explore(state), settings
        )
    except Exception:
        return ""
def _execution_failure(
    state: AgentState,
    *,
    sql: str,
    message: str,
    retries: int,
    exploration_block: str = "",
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
        "shape_retry": False,
        "retry_context": build_retry_context(
            previous_sql=sql,
            error=message,
            prior_context=state.get("retry_context") or "",
            retry_type=retry_type,
            exploration_block=exploration_block,
        ),
        "steps": steps,
    }

