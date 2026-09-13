"""Two-stage bidirectional schema linker prompts (dialect-agnostic)."""

from .base import render

TABLE_FIRST_PROMPT = """\
You are a database schema analyst.
Your task: identify which tables are needed to answer the user's question.

Available tables (names and short descriptions only):
{table_catalog}
-- Format: table_name: one-line description
-- Example:
-- orders: purchase transactions with customer, amount, status
-- customers: customer profile and contact information

Rules:
- Select the minimum set of tables necessary and sufficient to answer the question.
- Include tables needed for JOINs even if not directly mentioned.
- If unsure between two tables, include both.
- If the question groups, ranks, or filters by a named attribute of a related entity
  (not a raw id), include the FK target / lookup table — do not stop at the fact table
  that only stores *_id.
- When multiple candidate tables could represent the same concept, prefer the table
  that other tables in this schema explicitly reference via FOREIGN KEY — it is the
  authoritative source. A table that no other table references is likely derived or
  secondary; use it only when no authoritative source exists for the required data.
- When conversation history is present, keep tables needed to continue the prior metric
  (counts, quantities, amounts) while adding tables for any new dimension in the
  current question. Do not drop the prior fact tables.
- Think step by step before answering.

Return JSON only:
{{
  "reasoning": "step by step analysis of what the question needs",
  "selected_tables": ["table1", "table2"]
}}
"""

TABLE_FIRST_USER_PROMPT = """\
{conversation_history_block}Question: {user_question}
Current date: {current_date}
"""

COLUMN_FIRST_PROMPT = """\
You are a database schema analyst.
Your task: identify which specific columns are most relevant to the user's question, then derive their tables.

Full schema (all tables and columns):
{compact_schema}
-- Format: table.column (type) [description if available] FK→target.col when known

Rules:
- Identify columns for: SELECT projection, WHERE filters, JOIN keys, GROUP BY dimensions, ORDER BY fields.
- Think about what the question is measuring and what constraints it implies.
- Prefer human-label columns (name, title, label, code, display_name) on referenced
  tables over exposing raw FK id columns as the primary grouping dimension.
- When a compact schema line shows FK→target.table, include that target table's label
  columns if the question asks for a named dimension of that entity.
- When conversation history is present, keep columns needed for the prior metric while
  adding columns for the new dimension.

Return JSON only:
{{
  "reasoning": "what the question measures, what filters it needs, what groupings",
  "selected_columns": [
    {{"table": "orders", "column": "total_amount"}},
    {{"table": "orders", "column": "status"}},
    {{"table": "customers", "column": "name"}}
  ]
}}
"""

COLUMN_FIRST_USER_PROMPT = """\
{conversation_history_block}Question: {user_question}
Current date: {current_date}
"""


def _history_block(conversation_history: str = "") -> str:
    history = (conversation_history or "").strip()
    if not history:
        return ""
    return f"Conversation history (recent turns):\n{history}\n\n"


def render_table_first_prompt(
    user_question: str,
    table_catalog: str,
    current_date: str,
    conversation_history: str = "",
) -> tuple[str, str]:
    system = render(TABLE_FIRST_PROMPT, table_catalog=table_catalog)
    user = render(
        TABLE_FIRST_USER_PROMPT,
        user_question=user_question,
        current_date=current_date,
        conversation_history_block=_history_block(conversation_history),
    )
    return system, user


def render_column_first_prompt(
    user_question: str,
    compact_schema: str,
    current_date: str,
    conversation_history: str = "",
) -> tuple[str, str]:
    system = render(COLUMN_FIRST_PROMPT, compact_schema=compact_schema)
    user = render(
        COLUMN_FIRST_USER_PROMPT,
        user_question=user_question,
        current_date=current_date,
        conversation_history_block=_history_block(conversation_history),
    )
    return system, user
