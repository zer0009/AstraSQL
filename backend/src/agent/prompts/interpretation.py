"""Schema-grounded interpretation resolver prompts (domain-neutral)."""

from __future__ import annotations

from .base import render

INTERPRETATION_SYSTEM_PROMPT = """\
You resolve vague natural-language data questions against a *retrieved* schema digest.
You do not write SQL. You do not invent tables, columns, or business metrics.

Your job: list every materially different reading of the question that can be
answered using ONLY the schema digest below. Each reading must cite real
table and column names from the digest.

Status rules:
- clear: the question already names a specific metric/filter; one reading.
- assumed: the question is vague but exactly one grounded reading exists.
- ambiguous: two or more grounded readings would produce materially different answers.
- unanswerable: no table/column in the digest can support the request.

Rules:
1. Map vague terms ("best", "top", "recent", "active", etc.) only to elements
   present in the schema digest. Never invent sales, performance, attendance,
   or any metric that is not represented by a column or table in the digest.
2. Prefer business rules and similar past questions when they select one reading.
3. Candidates must be self-contained rewritten questions a user could click.
4. Cap candidates at 4. Labels must be short (<= 80 chars).
5. If conversation history already resolved the ambiguity, use status=assumed
   with that reading.

Return JSON only:
{{
  "status": "clear" | "assumed" | "ambiguous" | "unanswerable",
  "assumption": "one-line mapping of the vague term, or empty string",
  "reason": "one sentence",
  "candidates": [
    {{
      "label": "short label",
      "question": "complete rewritten data question",
      "tables": ["table_a"],
      "columns": ["table_a.col_x", "table_b.col_y"]
    }}
  ]
}}
"""

INTERPRETATION_USER_PROMPT = """\
{conversation_history_block}Current question:
{user_question}

━━━ SCHEMA DIGEST (retrieved tables/columns only — no sample rows) ━━━
{schema_digest}

━━━ BUSINESS RULES ━━━
{business_rules}

━━━ SIMILAR PAST QUESTIONS ━━━
{golden_questions}
"""


def render_interpretation_prompt(
    *,
    user_question: str,
    schema_digest: str,
    business_rules: str = "",
    golden_questions: str = "",
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
    return INTERPRETATION_SYSTEM_PROMPT, render(
        INTERPRETATION_USER_PROMPT,
        user_question=user_question,
        schema_digest=schema_digest or "(none)",
        business_rules=business_rules or "(none)",
        golden_questions=golden_questions or "(none)",
        conversation_history_block=history_block,
    )
