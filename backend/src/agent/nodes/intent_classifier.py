from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select

from src.agent.prompts.generator import format_conversation_history
from src.agent.prompts.intent import render_intent_prompt
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, get_configurable, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider

_VALID_INTENTS = frozenset({"SQL_QUERY", "META", "CHIT_CHAT"})
_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def _overlap_schema(question: str, table_names: list[str]) -> bool:
    """True when the question shares a content token with any table name."""
    q_tokens = {t.lower() for t in _TOKEN_RE.findall(question or "") if len(t) >= 3}
    if not q_tokens:
        return False
    for name in table_names:
        parts = {p.lower() for p in _TOKEN_RE.findall(name or "") if len(p) >= 3}
        # Also treat underscored names as a whole token.
        whole = (name or "").strip().lower()
        if whole:
            parts.add(whole)
        if q_tokens & parts:
            return True
    return False


async def _load_table_names(session: Any, connection_id: Any) -> list[str]:
    if session is None or connection_id is None:
        return []
    try:
        from src.storage.models import SchemaCache

        result = await session.execute(
            select(SchemaCache.table_name)
            .where(SchemaCache.connection_id == connection_id)
            .order_by(SchemaCache.table_name)
        )
        return [str(r[0]) for r in result.all() if r[0]]
    except Exception:
        return []


async def intent_classifier(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Classify the user question into SQL vs non-SQL intents (route-only)."""
    question = (state.get("question") or "").strip()
    settings = get_settings()
    history_text = format_conversation_history(
        state.get("conversation_history") or []
    )
    cfg = get_configurable(config)
    session = cfg.get("session")
    connection = cfg.get("connection")
    connection_id = state.get("connection_id") or getattr(connection, "id", None)
    table_names = await _load_table_names(session, connection_id)

    try:
        system, user = render_intent_prompt(
            question,
            conversation_history=history_text,
            schema_tables=table_names,
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

    # Schema overlap fail-open: never route a data question about known tables
    # away from SQL (fixes Spider no_sql misses like "How many continents").
    if intent != "SQL_QUERY" and _overlap_schema(question, table_names):
        intent = "SQL_QUERY"
        reason = (
            (reason + "; ") if reason else ""
        ) + "overridden to SQL_QUERY due to schema table overlap"

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
