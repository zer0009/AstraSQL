"""SQL generation node (single-path, multi-candidate, or merged interpret+generate)."""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.candidates import generate_and_select_candidates
from src.agent.prompts.generator import (
    format_conversation_history,
    render_generator_prompt,
    render_merged_generator_prompt,
)
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, get_configurable, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider


def _effective_candidate_count(settings: Any, retry_context: str) -> int:
    """Base setting, boosted to ≥2 on EMPTY_RESULT / SYNTAX / suspicious retries."""
    count = int(getattr(settings, "sql_candidate_count", 1) or 1)
    blob = (retry_context or "").upper()
    if (
        "EMPTY_RESULT" in blob
        or "SUSPICIOUS_RESULT" in blob
        or "SYNTAX_ERROR" in blob
        or "[SYNTAX" in blob
    ):
        count = max(count, 2)
    return max(1, min(count, 5))


def _assumption_from_state(state: AgentState) -> str:
    assumption = str(state.get("assumption") or "").strip()
    if assumption:
        return assumption
    amb = state.get("ambiguity") or {}
    if isinstance(amb, dict):
        return str(amb.get("assumption") or "").strip()
    return ""


async def query_generator(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Generate dialect-aware SQL from the user question and retrieved context."""
    cfg = get_configurable(config)
    db_provider = cfg.get("db_provider")
    settings = get_settings()

    if db_provider is None:
        return {
            "error": "Missing db_provider in configurable",
            "steps": append_step(state, "generate_error", "db_provider missing"),
        }

    context = state.get("context") or {}
    question = state.get("question") or ""
    retry_context = state.get("retry_context") or ""
    retries = int(state.get("retries") or 0)

    # Fatal upstream failure (e.g. context) — do not invent SQL.
    if state.get("error") and not context.get("enriched_schema"):
        return {
            "sql": "",
            "corrected_sql": "",
            "error": state.get("error"),
            "steps": append_step(
                state,
                "generate_skipped",
                state.get("error") or "Missing context; skipped SQL generation",
            ),
        }

    updates: dict[str, Any] = {"shape_retry": False}

    if retry_context.strip():
        retries = retries + 1
        updates["retries"] = retries

    candidate_count = _effective_candidate_count(settings, retry_context)
    merge = bool(getattr(settings, "merge_interpret_generate", False))
    # Difficulty router: escalate candidate count / disable merge on hard Qs.
    from src.agent.difficulty_router import route_generation_plan

    table_count = len(list(context.get("selected_tables") or []))
    plan = route_generation_plan(
        question,
        table_count=table_count,
        prior_failure=bool(retry_context.strip()),
        merge_interpret_generate=merge,
    )
    if int(plan.get("candidate_count") or 1) > candidate_count:
        candidate_count = int(plan["candidate_count"])
    # Merged path only on first attempt (no retry_context) when enabled/plan allows.
    use_merged = bool(plan.get("use_merge")) and not retry_context.strip()

    try:
        if use_merged:
            history_text = format_conversation_history(
                state.get("conversation_history") or []
            )
            system = render_merged_generator_prompt(
                dialect_name=db_provider.dialect_name(),
                enriched_schema=context.get("enriched_schema") or "",
                business_rules=context.get("business_rules") or "",
                golden_records=context.get("golden_records_text") or "",
                conversation_history=history_text,
                dialect_prompt_rules=db_provider.dialect_prompt_rules(),
                max_rows=settings.max_result_rows,
                retry_context=retry_context,
                user_question=question,
                current_date=date.today().isoformat(),
                schema_digest=context.get("schema_digest") or "",
            )
            llm = get_llm_provider().get_chat_model(
                temperature=0.0,
                max_tokens=settings.llm_max_tokens,
            )
            response = await llm.ainvoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=question or "Generate the SQL query."),
                ],
                config=config,
            )
            parsed = extract_json(message_text(response))
            status = str(parsed.get("status") or "assumed").strip().lower()
            sql = str(parsed.get("sql") or "").strip()

            if status == "not_a_data_question" or (
                not sql and status in {"not_a_data_question", "unanswerable"}
            ):
                if status == "not_a_data_question":
                    updates["intent"] = "CHIT_CHAT"
                elif status == "unanswerable":
                    updates["intent"] = "CLARIFICATION_NEEDED"
                updates["error"] = None
                updates["ambiguity"] = {
                    **(
                        state.get("ambiguity")
                        if isinstance(state.get("ambiguity"), dict)
                        else {}
                    ),
                    "should_clarify": status == "unanswerable",
                    "status": status,
                    "needs_execution_gate": False,
                    "decision_why": "merged_generate;not_sql",
                    "gate": "merged",
                    "reason": str(parsed.get("interpretation") or status),
                }
                updates["steps"] = append_step(
                    state,
                    "merged_non_sql",
                    f"Merged generator status={status}",
                    status=status,
                )
                return updates

            if not sql:
                raise ValueError("Merged generator returned empty SQL")

            interpretation = str(parsed.get("interpretation") or "").strip()
            assumptions = parsed.get("assumptions") or []
            if isinstance(assumptions, str):
                assumptions = [assumptions]
            decision_points = parsed.get("decision_points") or []
            if not isinstance(decision_points, list):
                decision_points = []
            dpoints = [str(p).strip() for p in decision_points if str(p).strip()]
            assumption_text = interpretation or (
                "; ".join(str(a) for a in assumptions if str(a).strip())
            )
            # Gate only when the model flags underspecification — not on every
            # assumed/clear answer (that made merge slower than the resolver path).
            needs_gate = bool(dpoints) or status == "ambiguous"

            updates["sql"] = sql
            updates["corrected_sql"] = sql
            updates["error"] = None
            if assumption_text:
                updates["assumption"] = assumption_text
            updates["ambiguity"] = {
                **(
                    state.get("ambiguity")
                    if isinstance(state.get("ambiguity"), dict)
                    else {}
                ),
                "should_clarify": False,
                "status": status,
                "assumption": assumption_text,
                "decision_points": dpoints,
                "needs_execution_gate": needs_gate,
                "decision_why": "merged_generate",
                "gate": "merged",
            }
            updates["steps"] = append_step(
                state,
                "sql_generated",
                f"Merged interpret+generate (retries={retries})",
                sql=sql,
                generation={
                    "merged": True,
                    "interpretation": interpretation,
                    "decision_points": dpoints,
                },
                retries=retries,
            )
            return updates

        if candidate_count > 1:
            sql, meta = await generate_and_select_candidates(
                state=state,
                config=config,
                db_provider=db_provider,
                settings=settings,
                candidate_count=candidate_count,
                question=question,
                retry_context=retry_context,
            )
            gen_steps = {"multi_candidate": meta}
        else:
            history_text = format_conversation_history(
                state.get("conversation_history") or []
            )
            assumption = _assumption_from_state(state)
            system = render_generator_prompt(
                dialect_name=db_provider.dialect_name(),
                enriched_schema=context.get("enriched_schema") or "",
                business_rules=context.get("business_rules") or "",
                golden_records=context.get("golden_records_text") or "",
                conversation_history=history_text,
                interpretation_assumption=assumption,
                dialect_prompt_rules=db_provider.dialect_prompt_rules(),
                max_rows=settings.max_result_rows,
                retry_context=retry_context,
                user_question=question,
                current_date=date.today().isoformat(),
            )
            llm = get_llm_provider().get_chat_model(
                temperature=0.0,
                max_tokens=settings.llm_max_tokens,
            )
            response = await llm.ainvoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=question or "Generate the SQL query."),
                ],
                config=config,
            )
            parsed = extract_json(message_text(response))
            sql = str(parsed.get("sql") or "").strip()
            if not sql:
                raise ValueError("Generator returned empty SQL")
            gen_steps = {
                k: parsed.get(k)
                for k in (
                    "step0_entities",
                    "step1_metric",
                    "step2_tables",
                    "step3_joins",
                    "step4_filters",
                    "step5_aggregation",
                    "step6_ordering",
                )
                if k in parsed
            }
    except Exception as exc:
        updates.update(
            {
                "sql": "",
                "corrected_sql": "",
                "error": f"SQL generation failed: {exc}",
                "steps": append_step(
                    state,
                    "generate_error",
                    str(exc),
                    retries=retries,
                ),
            }
        )
        return updates

    updates.update(
        {
            "sql": sql,
            "corrected_sql": sql,
            "error": None,
            "steps": append_step(
                state,
                "sql_generated",
                f"Generated SQL (attempt retries={retries})",
                sql=sql,
                generation=gen_steps,
                retries=retries,
                candidate_count=candidate_count,
            ),
        }
    )
    return updates
