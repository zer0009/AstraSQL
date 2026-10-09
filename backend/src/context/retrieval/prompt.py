from __future__ import annotations

from typing import Any

from src.config.settings import get_settings

# How many prior turns to fold into the FAISS / linker query text.
_LINK_HISTORY_TURNS = 3

def _build_link_query(
    question: str,
    conversation_history: list[dict[str, Any]] | None,
    *,
    max_turns: int = _LINK_HISTORY_TURNS,
) -> str:
    """FAISS / linker query: current question + recent prior questions/answers."""
    parts: list[str] = [question.strip()] if question and question.strip() else []
    if conversation_history:
        for turn in conversation_history[-max_turns:]:
            if not isinstance(turn, dict):
                continue
            prior_q = str(turn.get("question") or "").strip()
            prior_a = str(turn.get("answer") or "").strip()
            if prior_q:
                parts.append(prior_q)
            if prior_a:
                # Keep answer snippets short so embedding stays focused.
                parts.append(prior_a[:200])
    return "\n".join(parts) if parts else question


def _format_history_for_linker(
    conversation_history: list[dict[str, Any]] | None,
    *,
    max_turns: int = _LINK_HISTORY_TURNS,
) -> str:
    """Compact history text for schema-link LLM prompts."""
    if not conversation_history:
        return ""
    blocks: list[str] = []
    for index, turn in enumerate(conversation_history[-max_turns:], start=1):
        if not isinstance(turn, dict):
            continue
        q = str(turn.get("question") or "").strip()
        if not q:
            continue
        a = str(turn.get("answer") or "").strip()
        line = f"Turn {index} — User: {q}"
        if a:
            line += f"\n  Answer: {a[:180]}"
        blocks.append(line)
    return "\n".join(blocks)


_QUERY_EXPAND_SYSTEM = """\
You expand natural-language data questions into richer search phrases for schema retrieval.
Do NOT invent specific table or column names from any product. Stay database-agnostic.

Given a user question, return a short expansion that:
1. Names the business entities involved (people, places, products, documents, etc.)
2. Lists likely database representations as generic concepts
   (e.g. "geographic state/province/region lookup", "customer/partner master data",
   "product/item catalog", "order/transaction line items")
3. Notes the relationship type (comparison, cross-join, grouping, trend, filter)

Return plain text only — a single line or short paragraph of search keywords.
No JSON, no markdown, no SQL.
"""


async def _expand_link_query(question: str) -> str:
    """LLM-enrich the FAISS query with entity synonyms (database-agnostic).

    Falls back to the original question on any failure so retrieval still runs.
    When ``schema_link_expand`` is false (default), skip the LLM call.
    """
    text = (question or "").strip()
    if not text:
        return question

    settings = get_settings()
    if not bool(getattr(settings, "schema_link_expand", False)):
        return text

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.providers.llm import get_llm_provider, stage_chat_kwargs

        model_name = (
            (settings.expansion_model or "").strip()
            or (settings.enrichment_model or "").strip()
            or None
        )
        chat = get_llm_provider().get_chat_model(
            **stage_chat_kwargs(
                "expansion",
                settings=settings,
                model=model_name,
            )
        )
        response = await chat.ainvoke(
            [
                SystemMessage(content=_QUERY_EXPAND_SYSTEM),
                HumanMessage(content=text),
            ]
        )
        content = response.content
        if isinstance(content, list):
            expanded = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            ).strip()
        else:
            expanded = str(content).strip()
        if not expanded:
            return text
        # Combine original + expansion so exact terms still match embeddings.
        return f"{text}\n{expanded}"
    except Exception:
        return text
