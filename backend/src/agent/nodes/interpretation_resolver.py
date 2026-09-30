"""Schema-grounded interpretation resolver (ask vs proceed)."""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.ambiguity import (
    apply_interpretation_policy,
    build_schema_digest,
    build_schema_index,
    parse_interpretation_payload,
)
from src.agent.prompts.generator import format_conversation_history
from src.agent.prompts.interpretation import render_interpretation_prompt
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider

logger = logging.getLogger(__name__)


def _rules_from_text(text: str) -> list[str]:
    if not text or text.strip() == "(none)":
        return []
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped and stripped != "(none)":
            out.append(stripped)
    return out


def _golden_text(questions: list[str]) -> str:
    lines = [q.strip() for q in questions if str(q).strip()]
    if not lines:
        return "(none)"
    return "\n".join(f"- {q}" for q in lines[:10])


async def interpretation_resolver(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Propose schema-grounded readings; policy decides whether to ask."""
    settings = get_settings()
    question = (state.get("question") or "").strip()
    context = state.get("context") or {}
    history = state.get("conversation_history") or []

    # Feature flag off → passthrough (legacy: generate SQL immediately).
    if not settings.grounded_clarification_enabled:
        return {
            "steps": append_step(
                state,
                "interpretation_skipped",
                "grounded_clarification_enabled=false",
                decision_why="flag_off",
            ),
        }

    # Upstream already decided to clarify (e.g. rule conflict).
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict) and ambiguity.get("should_clarify"):
        return {
            "steps": append_step(
                state,
                "interpretation_skipped",
                "Upstream ambiguity already set should_clarify",
                decision_why="upstream_clarify",
            ),
        }

    selected_tables = list(context.get("selected_tables") or [])
    selected_columns = list(context.get("selected_columns") or [])
    schema_digest = context.get("schema_digest") or build_schema_digest(
        selected_tables,
        selected_columns,
    )
    rules_text = str(context.get("business_rules") or "")
    golden_questions = list(context.get("golden_questions") or [])
    history_text = format_conversation_history(history)

    started = time.perf_counter()
    proposal_raw: Any = None
    try:
        system, user = render_interpretation_prompt(
            user_question=question,
            schema_digest=schema_digest,
            business_rules=rules_text,
            golden_questions=_golden_text(golden_questions),
            conversation_history=history_text,
        )
        model_name = (settings.interpretation_model or "").strip()
        if not model_name:
            model_name = (settings.enrichment_model or "").strip()
        llm = get_llm_provider().get_chat_model(
            temperature=0.0,
            max_tokens=min(settings.llm_max_tokens, 2048),
            model=model_name or None,
        )
        response = await llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)],
            config=config,
        )
        proposal_raw = extract_json(message_text(response))
        proposal = parse_interpretation_payload(proposal_raw)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("interpretation_resolver failed open: %s", exc)
        return {
            "ambiguity": {
                "should_clarify": False,
                "reason": f"Resolver failed open: {exc}",
                "options": [],
                "status": "failed_open",
                "decision_why": "resolver_exception",
            },
            "steps": append_step(
                state,
                "interpretation_failed_open",
                str(exc),
                decision_why="resolver_exception",
                elapsed_ms=elapsed_ms,
            ),
        }

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    tables, column_pairs, bare_columns = build_schema_index(
        selected_tables,
        selected_columns,
    )
    decision = apply_interpretation_policy(
        proposal,
        question=question,
        tables=tables,
        column_pairs=column_pairs,
        bare_columns=bare_columns,
        rules=_rules_from_text(rules_text),
        golden_questions=golden_questions,
        conversation_history=history,
    )

    update: dict[str, Any] = {
        "ambiguity": {
            "should_clarify": decision.should_clarify,
            "reason": decision.reason,
            "options": decision.options,
            "status": decision.status,
            "decision_why": decision.decision_why,
            "assumption": decision.assumption,
        },
        "steps": append_step(
            state,
            "interpretation_resolved",
            (
                f"status={decision.status} clarify={decision.should_clarify} "
                f"why={decision.decision_why}"
            ),
            status=decision.status,
            should_clarify=decision.should_clarify,
            decision_why=decision.decision_why,
            elapsed_ms=elapsed_ms,
            candidate_count=len(proposal.candidates),
            option_count=len(decision.options),
        ),
    }

    if decision.assumption:
        update["assumption"] = decision.assumption

    if decision.should_clarify:
        update["intent"] = "CLARIFICATION_NEEDED"
        update["intent_reason"] = decision.reason
        if decision.options:
            update["clarification_options"] = decision.options
        # Surface alternatives even for unanswerable (Other only).
        if decision.status == "unanswerable":
            update["follow_ups"] = [
                f"What data is available in: {', '.join(sorted(tables)[:6])}?"
            ] if tables else []
    elif decision.options:
        # Alternatives as follow-ups when we assumed.
        update["follow_ups"] = decision.options

    # Persist digest for direct_response / META.
    if schema_digest and schema_digest != "(none)":
        ctx = dict(context)
        ctx["schema_digest"] = schema_digest
        update["context"] = ctx

    return update
