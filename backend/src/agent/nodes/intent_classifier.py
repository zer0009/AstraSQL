from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.prompts.generator import format_conversation_history
from src.agent.prompts.intent import render_intent_prompt
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider

_VALID_INTENTS = frozenset({"SQL_QUERY", "META", "CHIT_CHAT"})


async def intent_classifier(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Classify the user question into SQL vs non-SQL intents (route-only)."""
    question = (state.get("question") or "").strip()
    settings = get_settings()
    history_text = format_conversation_history(
        state.get("conversation_history") or []
    )

    try:
        system, user = render_intent_prompt(
            question,
            conversation_history=history_text,
        )
        model_name = (settings.intent_model or "").strip() or None
        llm = get_llm_provider().get_chat_model(
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
            model=model_name,
        )
        response = await llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)],
            config=config,
        )
        parsed = extract_json(message_text(response))
        intent = str(parsed.get("intent") or "SQL_QUERY").strip().upper()
        # Legacy label from older prompts — treat as data and let the
        # schema-grounded resolver decide whether to ask.
        if intent == "CLARIFICATION_NEEDED":
            intent = "SQL_QUERY"
        if intent not in _VALID_INTENTS:
            intent = "SQL_QUERY"
        reason = str(parsed.get("reason") or "").strip()
    except Exception as exc:
        # Fail open: keep the SQL path so schema grounding can still run.
        intent = "SQL_QUERY"
        reason = (
            f"Intent classification failed; defaulting to SQL_QUERY ({exc})"
        )

    return {
        "intent": intent,
        "intent_reason": reason,
        "error": None,
        "steps": append_step(
            state,
            "intent_classified",
            f"Intent={intent}: {reason}" if reason else f"Intent={intent}",
            intent=intent,
        ),
    }
