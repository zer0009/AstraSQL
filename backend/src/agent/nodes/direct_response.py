from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.prompts.generator import format_conversation_history
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider

_DIRECT_SYSTEM = """\
You are AstraSQL, a helpful database assistant.
The user's message does not require running a SQL query right now.

Intent: {intent}
Reason: {reason}

Respond helpfully in plain language.
- For META: answer about the database/product capabilities without inventing schema facts you do not know. If schema details are needed, ask the user to rephrase as a data question or check the Context page.
- For CLARIFICATION_NEEDED: ask 1–3 precise clarifying questions in "answer". Also provide 2–4 short rewritten question options the user can click in "clarification_options" (each option must be a complete, self-contained data question). If conversation history already answers part of the ambiguity, acknowledge what you know and only ask for what is still missing.
- For CHIT_CHAT: reply briefly and offer to help with data questions.

Return JSON only:
{{
  "answer": "your response",
  "clarification_options": ["optional rewritten question 1", "optional rewritten question 2"],
  "follow_up_suggestions": ["optional follow-up 1", "optional follow-up 2"]
}}
"""


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

    user_content = question
    if history_text:
        user_content = (
            "CONVERSATION HISTORY:\n"
            f"{history_text}\n\n"
            f"Current question:\n{question}"
        )

    clarification_options: list[str] = []
    try:
        system = _DIRECT_SYSTEM.format(intent=intent, reason=reason)
        llm = get_llm_provider().get_chat_model(
            temperature=0.3,
            max_tokens=settings.llm_max_tokens,
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
        clarification_options = [str(x).strip() for x in raw_options if str(x).strip()]
    except Exception as exc:
        if intent == "CLARIFICATION_NEEDED":
            answer = (
                "I need a bit more detail to answer that accurately. "
                f"{reason or str(exc)}"
            )
            clarification_options = [
                "What time period should I use?",
                "Which metric should I measure?",
                "Which tables or entities are you asking about?",
            ]
        elif intent == "META":
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
            "Show me recent orders",
        ]

    if not answer:
        answer = reason or "How can I help with your data?"

    # Only surface clickable clarifications for CLARIFICATION_NEEDED.
    if intent != "CLARIFICATION_NEEDED":
        clarification_options = []

    return {
        "answer": answer,
        "key_finding": "",
        "assumption": None,
        "follow_ups": follow_ups,
        "clarification_options": clarification_options,
        "confidence": "HIGH",
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
