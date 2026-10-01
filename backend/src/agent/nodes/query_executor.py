from __future__ import annotations



from typing import Any



from langchain_core.runnables import RunnableConfig



from src.agent.provenance import clarify_or_none, clarify_unbound

from src.agent.result_shape import analyze_result_shape, empty_result_message

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

            if find_bind_placeholders(sql) or classify_retry_type(

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



        # Soft EMPTY_RESULT retry once (retries < 1). Clears results and sets

        # shape_retry so route_after_execute regenerates without a hard error.

        if shape.get("should_retry_empty"):

            message = empty_result_message(sql)

            return {

                "results": {},

                "error": None,

                "shape_retry": True,

                "retry_context": build_retry_context(

                    previous_sql=sql,

                    error=message,

                    prior_context=state.get("retry_context") or "",

                    retry_type="EMPTY_RESULT",

                ),

                "steps": append_step(

                    state,

                    "shape_retry_empty",

                    message,

                    sql=sql,

                    row_count=0,

                    warnings=warnings,

                    retry_type="EMPTY_RESULT",

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


