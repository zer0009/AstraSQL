"""Bounded tool-using repair step after execution evidence fails.

Tools: run_sql (limited), sample_values, describe_table. Cap steps and cost.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.utils import extract_json, message_text
from src.providers.llm import get_llm_provider, stage_chat_kwargs

logger = logging.getLogger(__name__)

_REPAIR_SYSTEM = """\
You are repairing a failed SQL query for {dialect}.
You may call tools by returning JSON:
{{
  "action": "sample_values" | "describe_table" | "run_sql" | "finish",
  "table": "optional table name",
  "column": "optional column name",
  "sql": "optional SELECT to try",
  "reason": "short reason"
}}
Rules:
- Only SELECT / WITH queries for run_sql.
- Prefer sample_values / describe_table before rewriting SQL.
- When ready, action=finish with the corrected sql.
- Stay within the provided schema tables/columns.
"""


async def _sample_values(
    db_provider: Any, table: str, column: str, settings: Any
) -> str:
    if not table or not column:
        return "sample_values requires table and column"
    try:
        from src.agent.column_explore import explore_for_repair

        return await explore_for_repair(
            db_provider, [(table, column)], settings
        ) or "(no samples)"
    except Exception as exc:
        return f"sample_values failed: {exc}"


async def _describe_table(context: dict[str, Any], table: str) -> str:
    schema = str(context.get("enriched_schema") or "")
    if not table:
        return "describe_table requires table"
    # Return the CREATE TABLE block that mentions the table.
    chunks = schema.split("\n\n")
    for chunk in chunks:
        if f"-- TABLE: {table}" in chunk or f"CREATE TABLE {table}" in chunk:
            return chunk[:2500]
    # Fallback: list selected columns for the table.
    cols = [
        f"{c.get('table')}.{c.get('column')}"
        for c in (context.get("selected_columns") or [])
        if isinstance(c, dict) and str(c.get("table")) == table
    ]
    if cols:
        return "Columns: " + ", ".join(cols[:40])
    return f"(no description for {table})"


async def _run_sql(db_provider: Any, sql: str, settings: Any) -> str:
    text = (sql or "").strip()
    if not text:
        return "run_sql requires sql"
    upper = text.upper()
    if any(tok in upper for tok in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE")):
        return "DML/DDL blocked"
    try:
        results = await db_provider.execute_readonly(
            text, max_rows=min(20, int(settings.max_result_rows or 20))
        )
        return json.dumps(
            {
                "row_count": results.get("row_count"),
                "columns": results.get("columns"),
                "rows": (results.get("rows") or [])[:5],
            },
            default=str,
        )[:2000]
    except Exception as exc:
        return f"execute failed: {exc}"


async def run_repair_agent(
    *,
    state: dict[str, Any],
    db_provider: Any,
    settings: Any,
    error: str,
) -> dict[str, Any]:
    """Run a bounded repair loop. Returns ``{sql?, observations, steps_used}``."""
    if not bool(getattr(settings, "repair_agent_enabled", True)):
        return {"sql": None, "observations": [], "steps_used": 0, "skipped": True}

    max_steps = int(getattr(settings, "repair_max_steps", 3) or 3)
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    dialect = ""
    try:
        dialect = str(db_provider.dialect_name() or "")
    except Exception:
        dialect = "SQL"

    previous_sql = (state.get("corrected_sql") or state.get("sql") or "").strip()
    question = str(state.get("question") or "")
    observations: list[str] = []
    proposed_sql: str | None = None

    llm = get_llm_provider().get_chat_model(
        **stage_chat_kwargs("repair_agent", settings=settings, escalate=True)
    )
    system = _REPAIR_SYSTEM.format(dialect=dialect)
    history = (
        f"Question: {question}\n"
        f"Failed SQL: {previous_sql[:800]}\n"
        f"Error: {error}\n"
        f"Schema tables: {', '.join(list(context.get('selected_tables') or [])[:20])}\n"
    )

    for step in range(max_steps):
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(
                        content=history
                        + "\nObservations:\n"
                        + ("\n".join(observations[-6:]) or "(none)")
                        + "\n\nReturn the next JSON action."
                    ),
                ]
            )
            parsed = extract_json(message_text(response))
        except Exception as exc:
            observations.append(f"step{step}: llm_failed:{exc}")
            break

        action = str(parsed.get("action") or "finish").strip().lower()
        table = str(parsed.get("table") or "").strip()
        column = str(parsed.get("column") or "").strip()
        sql = str(parsed.get("sql") or "").strip()
        reason = str(parsed.get("reason") or "").strip()

        if action == "sample_values":
            obs = await _sample_values(db_provider, table, column, settings)
            observations.append(f"sample_values({table}.{column}): {obs[:500]}")
            continue
        if action == "describe_table":
            obs = await _describe_table(context, table)
            observations.append(f"describe_table({table}): {obs[:500]}")
            continue
        if action == "run_sql":
            obs = await _run_sql(db_provider, sql, settings)
            observations.append(f"run_sql: {obs}")
            if "execute failed" not in obs and sql:
                proposed_sql = sql
            continue
        # finish
        if sql:
            proposed_sql = sql
        observations.append(f"finish: {reason or 'done'}")
        break

    return {
        "sql": proposed_sql,
        "observations": observations,
        "steps_used": len(observations),
        "skipped": False,
    }
