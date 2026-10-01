"""Schema-grounded interpretation resolver (ask vs proceed)."""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.ambiguity import (
    PolicyDecision,
    apply_interpretation_policy,
    build_schema_digest,
    build_schema_index,
    parse_interpretation_payload,
    validate_candidates,
)
from src.agent.prompts.generator import format_conversation_history
from src.agent.prompts.interpretation import render_interpretation_prompt
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, get_configurable, message_text
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


def _grounded_clarification_enabled(connection: Any, settings: Any) -> bool:
    """Connection override (None → settings.grounded_clarification_enabled)."""
    if connection is not None:
        flag = getattr(connection, "grounded_clarification_enabled", None)
        if flag is not None:
            return bool(flag)
    return bool(settings.grounded_clarification_enabled)


def _force_assume_only(
    decision: PolicyDecision,
    *,
    proposal: Any,
    tables: set[str],
    column_pairs: set[tuple[str, str]],
    bare_columns: set[str],
) -> PolicyDecision:
    """Rewrite a clarify decision into assumed proceed (interpretation_mode=assume_only)."""
    if not decision.should_clarify:
        return decision
    selected = decision.selected
    if selected is None:
        valid = validate_candidates(
            proposal.candidates,
            tables=tables,
            column_pairs=column_pairs,
            bare_columns=bare_columns,
        )
        selected = valid[0] if valid else None
    options = [
        o
        for o in (decision.options or [])
        if "Other" not in o and (selected is None or o != selected.question)
    ][:3]
    if selected is None and not options:
        options = decision.options or []
    return PolicyDecision(
        should_clarify=False,
        status="assumed" if selected is not None else decision.status,
        reason=decision.reason or "assume_only mode; proceeding without clarification",
        assumption=decision.assumption
        or (
            f"Assumed: {selected.label or selected.question}" if selected else ""
        ),
        options=options,
        decision_why=f"assume_only;was={decision.decision_why}",
        selected=selected,
        needs_execution_gate=decision.needs_execution_gate,
        decision_points=decision.decision_points,
    )


async def interpretation_resolver(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Propose schema-grounded readings; policy decides whether to ask."""
    settings = get_settings()
    cfg = get_configurable(config)
    connection = cfg.get("connection")
    question = (state.get("question") or "").strip()
    context = state.get("context") or {}
    history = state.get("conversation_history") or []

    mode = (settings.interpretation_mode or "on").strip().lower()
    if mode not in {"on", "off", "assume_only"}:
        mode = "on"

    # Feature flag / mode off → passthrough (legacy: generate SQL immediately).
    if mode == "off" or not _grounded_clarification_enabled(connection, settings):
        why = "interpretation_mode=off" if mode == "off" else "grounded_clarification_enabled=false"
        return {
            "steps": append_step(
                state,
                "interpretation_skipped",
                why,
                decision_why=why,
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
        fk_edges=context.get("fk_edges"),
        column_types=context.get("column_types"),
        example_values=context.get("example_values"),
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
    defer_gate = bool(getattr(settings, "execution_evidence_gate", True))
    decision = apply_interpretation_policy(
        proposal,
        question=question,
        tables=tables,
        column_pairs=column_pairs,
        bare_columns=bare_columns,
        rules=_rules_from_text(rules_text),
        golden_questions=golden_questions,
        conversation_history=history,
        defer_ask_to_execution_gate=defer_gate and mode == "on",
    )
    if mode == "assume_only":
        decision = _force_assume_only(
            decision,
            proposal=proposal,
            tables=tables,
            column_pairs=column_pairs,
            bare_columns=bare_columns,
        )

    candidates_payload = [
        {
            "label": c.label,
            "question": c.question,
            "tables": list(c.tables),
            "columns": list(c.columns),
        }
        for c in proposal.candidates
    ]
    selected_payload = None
    if decision.selected is not None:
        selected_payload = {
            "label": decision.selected.label,
            "question": decision.selected.question,
            "tables": list(decision.selected.tables),
            "columns": list(decision.selected.columns),
        }
    update: dict[str, Any] = {
        "ambiguity": {
            "should_clarify": decision.should_clarify,
            "reason": decision.reason,
            "options": decision.options,
            "status": decision.status,
            "decision_why": decision.decision_why,
            "assumption": decision.assumption,
            "proposal_status": proposal.status,
            "candidates": candidates_payload,
            "selected": selected_payload,
            "needs_execution_gate": decision.needs_execution_gate,
            "decision_points": list(decision.decision_points),
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
            proposal_status=proposal.status,
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
