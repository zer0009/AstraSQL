"""Intent classifier prompts."""

from .base import render

INTENT_SYSTEM_PROMPT = """\
You are a query intent classifier for a database assistant.

Classify the user's message into exactly one of:
- SQL_QUERY: The user is asking for data that requires querying a database
  (counts, lists, aggregations, comparisons, trends, filters, rankings,
  "best/top/latest" style questions). Prefer SQL_QUERY whenever the message
  is about data — even if the metric is vague. A later schema-grounded step
  decides whether to ask for clarification.
- META: The user is asking about the database itself (what tables exist,
  what does column X mean, how to connect, who has access).
- CHIT_CHAT: Greetings or questions unrelated to data.

Rules:
- Prefer SQL_QUERY for ordinary data questions even if slightly vague
  ("how many partners", "latest orders", "best employee", "revenue in 2025").
- If AVAILABLE TABLES is provided and the question mentions or clearly refers
  to any of those tables (or their subject), classify as SQL_QUERY.
- Do NOT classify as META just because the question is ambiguous.
- Do NOT invent example account numbers, IDs, or dates in the reason field.
- When CONVERSATION HISTORY is present, resolve pronouns and references using
  that history ("these customers", "them", "that period", "same filter").
  If prior turns already identify the entities or filters, classify as SQL_QUERY.
- This product maps no login to a table row. Still classify data questions as
  SQL_QUERY — do not invent an id.

Return JSON only:
{{
  "intent": "SQL_QUERY" | "META" | "CHIT_CHAT",
  "reason": "one sentence"
}}
"""

INTENT_USER_PROMPT = """\
{conversation_history_block}{schema_tables_block}Current question:
{user_question}
"""


def render_intent_prompt(
    user_question: str,
    conversation_history: str = "",
    schema_tables: list[str] | None = None,
) -> tuple[str, str]:
    history = (conversation_history or "").strip()
    if history:
        history_block = (
            "CONVERSATION HISTORY (prior turns — use to resolve references):\n"
            f"{history}\n\n"
        )
    else:
        history_block = ""
    tables = [str(t).strip() for t in (schema_tables or []) if str(t).strip()]
    if tables:
        preview = ", ".join(tables[:40])
        more = f" (+{len(tables) - 40} more)" if len(tables) > 40 else ""
        schema_tables_block = (
            "AVAILABLE TABLES (prefer SQL_QUERY when the question relates):\n"
            f"{preview}{more}\n\n"
        )
    else:
        schema_tables_block = ""
    return INTENT_SYSTEM_PROMPT, render(
        INTENT_USER_PROMPT,
        user_question=user_question,
        conversation_history_block=history_block,
        schema_tables_block=schema_tables_block,
    )
