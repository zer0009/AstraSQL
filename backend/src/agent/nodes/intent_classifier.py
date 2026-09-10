from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.prompts.intent import render_intent_prompt
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider

_VALID_INTENTS = frozenset(
    {"SQL_QUERY", "META", "CLARIFICATION_NEEDED", "CHIT_CHAT"}
)


async def intent_classifier(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Classify the user question into SQL vs non-SQL intents."""
    question = (state.get("question") or "").strip()
    settings = get_settings()

    try:
        system, user = render_intent_prompt(question)
        llm = get_llm_provider().get_chat_model(
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
        )
        response = await llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)],
            config=config,
        )
        parsed = extract_json(message_text(response))
        intent = str(parsed.get("intent") or "SQL_QUERY").strip().upper()
        if intent not in _VALID_INTENTS:
            intent = "SQL_QUERY"
        reason = str(parsed.get("reason") or "").strip()
    except Exception as exc:
        intent = "SQL_QUERY"
        reason = f"Intent classification failed; defaulting to SQL_QUERY ({exc})"

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
