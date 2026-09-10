from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.agent.state import AgentState
from src.agent.utils import append_step, get_configurable, max_retries
from src.context.retriever import ContextRetriever


async def context_retriever_node(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Retrieve schema, rules, and golden records for SQL generation."""
    cfg = get_configurable(config)
    session = cfg.get("session")
    connection = cfg.get("connection")
    db_provider = cfg.get("db_provider")

    if session is None or connection is None or db_provider is None:
        return {
            "error": "Missing session, connection, or db_provider in configurable",
            "retries": max_retries(),
            "steps": append_step(
                state,
                "context_error",
                "RunnableConfig.configurable is incomplete",
            ),
        }

    connection_id = state.get("connection_id") or getattr(connection, "id", None)
    question = state.get("question") or ""

    try:
        retrieved = await ContextRetriever().get(
            session,
            connection_id,
            question,
            db_provider,
        )
    except Exception as exc:
        return {
            "error": f"Context retrieval failed: {exc}",
            "retries": max_retries(),
            "steps": append_step(
                state,
                "context_error",
                str(exc),
            ),
        }

    context = {
        "enriched_schema": retrieved.enriched_schema,
        "business_rules": retrieved.business_rules,
        "golden_records_text": retrieved.golden_records_text,
        "selected_tables": retrieved.selected_tables,
        "selected_columns": retrieved.selected_columns,
    }

    steps = list(state.get("steps") or [])
    for ctx_step in retrieved.steps:
        steps.append(
            {
                "name": ctx_step.get("step") or "context",
                "detail": ctx_step.get("detail") or "",
                **{
                    k: v
                    for k, v in ctx_step.items()
                    if k not in {"step", "detail"}
                },
            }
        )
    steps.append(
        {
            "name": "context_retrieved",
            "detail": (
                f"Linked {len(retrieved.selected_tables)} tables "
                f"for SQL generation"
            ),
            "tables": retrieved.selected_tables,
        }
    )

    return {
        "context": context,
        "error": None,
        "steps": steps,
    }
