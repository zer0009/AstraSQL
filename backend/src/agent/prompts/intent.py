"""Intent classifier prompts."""

from .base import render

INTENT_SYSTEM_PROMPT = """\
You are a query intent classifier for a database assistant.

Classify the user's message into exactly one of:
- SQL_QUERY: The user is asking for data that requires querying a database (counts, lists, aggregations, comparisons, trends, filters on data).
- META: The user is asking about the database itself (what tables exist, what does column X mean, how to connect, who has access).
- CLARIFICATION_NEEDED: The question is missing a required filter that cannot be reasonably defaulted (e.g. "show me the report" with no subject). Prefer SQL_QUERY when a sensible default exists.
- CHIT_CHAT: Greetings or questions unrelated to data.

Rules:
- Prefer SQL_QUERY for ordinary data questions even if slightly vague ("how many partners", "latest orders", "revenue in 2025"). The SQL generator can apply sensible defaults.
- Use CLARIFICATION_NEEDED only when two or more interpretations would produce materially different queries and no default is safe.
- Do NOT invent example account numbers, IDs, or dates in the reason field.
- When CONVERSATION HISTORY is present, resolve pronouns and references using that history ("these customers", "them", "that period", "same filter", "for each of those"). If prior turns already identify the entities or filters, classify as SQL_QUERY — do not ask the user to repeat what is already in history.
- Only use CLARIFICATION_NEEDED for follow-ups when history does not resolve the ambiguity.

Return JSON only:
{{
  "intent": "SQL_QUERY" | "META" | "CLARIFICATION_NEEDED" | "CHIT_CHAT",
  "reason": "one sentence"
}}
"""

INTENT_USER_PROMPT = """\
{conversation_history_block}Current question:
{user_question}
"""


def render_intent_prompt(
    user_question: str,
    conversation_history: str = "",
) -> tuple[str, str]:
    history = (conversation_history or "").strip()
    if history:
        history_block = (
            "CONVERSATION HISTORY (prior turns — use to resolve references):\n"
            f"{history}\n\n"
        )
    else:
        history_block = ""
    return INTENT_SYSTEM_PROMPT, render(
        INTENT_USER_PROMPT,
        user_question=user_question,
        conversation_history_block=history_block,
    )
