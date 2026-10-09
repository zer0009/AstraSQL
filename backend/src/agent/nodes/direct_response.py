from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.execution_gate import (
    ensure_other_option,
    is_generic_gate_option,
)
from src.agent.prompts.generator import format_conversation_history
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider, stage_chat_kwargs

_DIRECT_SYSTEM = """\
You are AstraSQL, a helpful database assistant.
The user's message does not require running a SQL query right now.

Intent: {intent}
Reason: {reason}

{schema_block}

Respond helpfully in plain language.
- For META: answer using ONLY the schema digest above when present. Do not
  invent tables, columns, or metrics that are not listed. If the digest is
  empty, say you need a scanned connection / Context page.
- For CLARIFICATION_NEEDED: ask 1–2 precise clarifying questions in "answer"
  grounded ONLY in the schema digest and the provided options. Never suggest
  metrics (e.g. sales, performance) that are not represented in the digest.
  Also return clarification_options: 2–4 short, clickable choices that answer
  those questions (same language as the user). Prefer refining the provided
  options into natural labels (e.g. "Group by country and state", "All orders")
  over opaque technical diffs. Each option should be a self-contained choice
  the user can tap. Always include room for the user to rephrase (Other is
  added automatically). If conversation history already answers part of the
  ambiguity, acknowledge what you know and only ask for what is still missing.
- For CHIT_CHAT: reply briefly and offer to help with data questions.

Return JSON only:
{{
  "answer": "your response",
  "clarification_options": ["optional rewritten question 1", "optional rewritten question 2"],
  "follow_up_suggestions": ["optional follow-up 1", "optional follow-up 2"]
}}
"""


def _schema_block(context: dict[str, Any] | None, intent: str) -> str:
    if intent not in {"CLARIFICATION_NEEDED", "META"}:
        return ""
    digest = ""
    if isinstance(context, dict):
        digest = str(context.get("schema_digest") or "").strip()
        if not digest or digest == "(none)":
            tables = context.get("selected_tables") or []
            if tables:
                digest = "Tables: " + ", ".join(str(t) for t in tables[:30])
    if not digest:
        return (
            "━━━ SCHEMA DIGEST ━━━\n"
            "(none available for this turn)\n"
        )
    # Bound prompt size.
    if len(digest) > 6000:
        digest = digest[:6000] + "\n…(truncated)"
    return (
        "━━━ SCHEMA DIGEST (retrieved only — do not invent beyond this) ━━━\n"
        f"{digest}\n"
    )


async def direct_response(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Answer META / CHIT_CHAT / CLARIFICATION intents without querying the DB."""
    settings = get_settings()
    intent = (state.get("intent") or "CHIT_CHAT").upper()
    reason = state.get("intent_reason") or ""
    question = state.get("question") or ""
    history_text = format_conversation_history(
        state.get("conversation_history") or []
    )
    context = state.get("context") or {}

    user_content = question
    if history_text:
        user_content = (
            "CONVERSATION HISTORY:\n"
            f"{history_text}\n\n"
            f"Current question:\n{question}"
        )

    preset_options = [
        str(x).strip()
        for x in (state.get("clarification_options") or [])
        if str(x).strip()
    ]
    ambiguity = state.get("ambiguity") or {}
    if isinstance(ambiguity, dict):
        for opt in ambiguity.get("options") or []:
            text = str(opt).strip()
            if text and text not in preset_options:
                preset_options.append(text)

    if preset_options and intent == "CLARIFICATION_NEEDED":
        user_content += (
            "\n\nPreferred clarification options (schema-validated; keep faithful):\n"
            + "\n".join(f"- {o}" for o in preset_options[:6])
        )

    clarification_options: list[str] = []
    try:
        system = _DIRECT_SYSTEM.format(
            intent=intent,
            reason=reason,
            schema_block=_schema_block(context, intent),
        )
        llm = get_llm_provider().get_chat_model(
            **stage_chat_kwargs(
                "direct_response",
                settings=settings,
                temperature=0.3,
            )
        )
        response = await llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user_content)],
            config=config,
        )
        parsed = extract_json(message_text(response))
        answer = str(parsed.get("answer") or "").strip()
        follow_ups = parsed.get("follow_up_suggestions") or []
        if not isinstance(follow_ups, list):
            follow_ups = [str(follow_ups)]
        follow_ups = [str(x) for x in follow_ups if x]
        raw_options = parsed.get("clarification_options") or []
        if not isinstance(raw_options, list):
            raw_options = [str(raw_options)]
        clarification_options = [
            str(x).strip() for x in raw_options if str(x).strip()
        ]
    except Exception as exc:
        if intent == "CLARIFICATION_NEEDED":
            answer = (
                "I need a bit more detail to answer that accurately. "
                f"{reason or str(exc)}"
            )
            clarification_options = preset_options or [
                "Other — I'll rephrase the question",
            ]
        elif intent == "META":
            digest = ""
            if isinstance(context, dict):
                digest = str(context.get("schema_digest") or "").strip()
            if digest and digest != "(none)":
                answer = (
                    "Here is what I can see from the retrieved schema:\n"
                    f"{digest[:2000]}"
                )
            else:
                answer = (
                    "I can help explore your connected database schema and run "
                    "read-only analytical questions. Ask about counts, trends, "
                    "or filters on your data."
                )
        else:
            answer = (
                "Hello! Ask me a question about your data and I'll generate "
                "SQL to answer it."
            )
        follow_ups = [
            "What tables are available?",
            "Show me a sample of recent rows",
        ]

    if not answer:
        answer = reason or "How can I help with your data?"

    # Only surface clickable clarifications for CLARIFICATION_NEEDED.
    if intent != "CLARIFICATION_NEEDED":
        clarification_options = []
    else:
        llm_opts = [
            o for o in clarification_options if o and not is_generic_gate_option(o)
        ]
        preset_concrete = [
            o for o in preset_options if o and not is_generic_gate_option(o)
        ]
        preset_generic = [
            o for o in preset_options if o and is_generic_gate_option(o)
        ]
        # Prefer natural-language options (LLM or concrete gate labels) over
        # opaque "Use reading where: Different SQL…" placeholders.
        if llm_opts:
            clarification_options = llm_opts
        elif preset_concrete:
            clarification_options = preset_concrete
        elif preset_options:
            clarification_options = preset_options
        # Keep any non-generic presets the LLM missed (e.g. Group by …).
        for opt in preset_concrete:
            if opt not in clarification_options:
                clarification_options.append(opt)
        # Drop leftover generic placeholders once we have real choices.
        if any(not is_generic_gate_option(o) for o in clarification_options):
            clarification_options = [
                o for o in clarification_options if not is_generic_gate_option(o)
            ]
        elif preset_generic and not clarification_options:
            clarification_options = preset_generic
        clarification_options = ensure_other_option(clarification_options)

    return {
        "answer": answer,
        "key_finding": "",
        "assumption": None,
        "follow_ups": follow_ups,
        "clarification_options": clarification_options,
        "confidence": "HIGH",
        "trust_level": "clarifying" if intent == "CLARIFICATION_NEEDED" else "guessed",
        "sql": "",
        "results": {"columns": [], "rows": [], "row_count": 0},
        "error": None,
        "steps": append_step(
            state,
            "direct_response",
            f"Responded without SQL (intent={intent})",
            intent=intent,
        ),
    }
