from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from src.agent.ambiguity import build_schema_digest, decide_ambiguity
from src.agent.state import AgentState
from src.agent.utils import append_step, get_configurable, max_retries
from src.context.retriever import ContextRetriever


def _rules_from_text(text: str) -> list[str]:
    if not text or text.strip() == "(none)":
        return []
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped and stripped != "(none)":
            out.append(stripped)
    return out


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
    conversation_history = state.get("conversation_history") or []

    try:
        retrieved = await ContextRetriever().get(
            session,
            connection_id,
            question,
            db_provider,
            conversation_history=conversation_history,
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

    business_rules = retrieved.business_rules or ""
    evidence = (state.get("evidence") or "").strip()
    if evidence:
        block = f"External knowledge for this question:\n{evidence}"
        if business_rules and business_rules.strip() not in {"", "(none)"}:
            business_rules = f"{business_rules.rstrip()}\n\n{block}"
        else:
            business_rules = block

    context = {
        "enriched_schema": retrieved.enriched_schema,
        "business_rules": business_rules,
        "golden_records_text": retrieved.golden_records_text,
        "selected_tables": retrieved.selected_tables,
        "selected_columns": retrieved.selected_columns,
        "identity_keys": retrieved.identity_keys,
        "used_golden": retrieved.used_golden,
        "golden_sqls": retrieved.golden_sqls,
        "golden_questions": retrieved.golden_questions,
        "verified_sql": retrieved.verified_sql or "",
        "fk_edges": list(retrieved.fk_edges or []),
        "column_types": dict(retrieved.column_types or {}),
        "example_values": dict(retrieved.example_values or {}),
        "schema_digest": build_schema_digest(
            retrieved.selected_tables,
            retrieved.selected_columns,
            fk_edges=retrieved.fk_edges,
            column_types=retrieved.column_types,
            example_values=retrieved.example_values,
        ),
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
    from src.config.settings import get_settings

    settings = get_settings()
    # When the execution-evidence gate is on, skip early rule-conflict asks here;
    # the schema-grounded resolver + gate handle ambiguity with SQL evidence.
    # Relationship edges in the semantic layer must not trigger "conflicting rules".
    if bool(getattr(settings, "execution_evidence_gate", True)):
        decision_should = False
        decision_reason = "Deferred to schema-grounded / execution-evidence path"
        decision_options: list[str] = []
    else:
        early = decide_ambiguity(
            question,
            rules=_rules_from_text(retrieved.business_rules),
            golden_questions=retrieved.golden_questions,
        )
        decision_should = early.should_clarify
        decision_reason = early.reason
        decision_options = list(early.options or [])
    ambiguity = {
        "should_clarify": decision_should,
        "reason": decision_reason,
        "options": decision_options,
    }
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
    if decision_should:
        steps.append(
            {
                "name": "ambiguity_gate",
                "detail": decision_reason,
            }
        )

    update: dict[str, Any] = {
        "context": context,
        "used_golden": retrieved.used_golden,
        "ambiguity": ambiguity,
        "error": None,
        "steps": steps,
    }
    # Merged path skips intent_classifier — default to SQL until generator says otherwise.
    if not state.get("intent"):
        update["intent"] = "SQL_QUERY"
    if decision_should:
        update["intent"] = "CLARIFICATION_NEEDED"
        update["intent_reason"] = decision_reason
        if decision_options:
            update["clarification_options"] = decision_options
    return update
